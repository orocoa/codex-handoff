#!/usr/bin/env python3
"""Advisory only: count canonical local compaction records; never launch or block."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


CACHE_SCHEMA = 'codex-compaction-scan-v1'
HASH_CHUNK = 1024 * 1024
CACHE_MIN_BYTES = 4 * 1024 * 1024


def _scan(stream, seen=None, malformed=0, offset=0, digest=None):
    """Scan complete lines; checkpoint before a partial tail so it is retried."""
    seen = set() if seen is None else seen
    partial_tail = False
    for line in stream:
        if not line.endswith(b'\n'):
            partial_tail = True
            break
        if digest is not None:
            digest.update(line)
        offset += len(line)
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            malformed += 1
            continue
        if not isinstance(row, dict) or row.get('type') != 'compacted':
            continue
        payload = row.get('payload')
        if not isinstance(payload, dict):
            malformed += 1
            continue
        # Preserve canonical ID/ordinal/full-row fallback and string coercion.
        # Hash even IDs before caching: an unusual ID must not persist text.
        key = payload.get('compaction_response_id') or payload.get('window_id')
        if not key:
            key = ('ordinal', row['ordinal']) if 'ordinal' in row else hashlib.sha256(
                json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        seen.add(hashlib.sha256(str(key).encode('utf-8', 'surrogatepass')).hexdigest())
    return seen, malformed, partial_tail, offset, digest


def count_compactions(transcript):
    with Path(transcript).open('rb') as stream:
        seen, malformed, partial_tail, _, _ = _scan(stream)
    return len(seen), malformed, partial_tail


def _private_lock(path):
    """Use a stable inode independent of the atomically replaced state file."""
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    return os.fdopen(fd, 'a+')


def _atomic_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _checksum(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _hex_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _read_cache(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return None
        checksum = data.pop('checksum', None)
        if checksum != _checksum(data) or data.get('schema') != CACHE_SCHEMA:
            return None
        if any(type(data.get(k)) is not int or data[k] < 0
               for k in ('device', 'inode', 'offset', 'malformed')):
            return None
        seen = data.get('seen')
        if (not _hex_digest(data.get('prefix_sha256')) or not isinstance(seen, list)
                or any(not _hex_digest(key) for key in seen) or len(set(seen)) != len(seen)):
            return None
        return data
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def _file_version(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _cached_count(transcript, thread_id, state_dir):
    """Validate every cached prefix byte; avoid only repeated JSON decoding.

    The transcript need not be append-only. A changed/replaced/truncated prefix
    forces a full parse. Cache problems and contention fall back to normal work.
    """
    transcript, state_dir = Path(transcript), Path(state_dir)
    name = hashlib.sha256(thread_id.encode()).hexdigest()[:24]
    cache = state_dir / (name + '.scan')
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with _private_lock(state_dir / (name + '.scan.lock')):
            previous = _read_cache(cache)
            with transcript.open('rb') as stream:
                before = os.fstat(stream.fileno())
                digest = hashlib.sha256()
                offset, malformed, seen = 0, 0, set()
                if (previous and previous['device'] == before.st_dev
                        and previous['inode'] == before.st_ino
                        and previous['offset'] <= before.st_size):
                    remaining = previous['offset']
                    while remaining:
                        chunk = stream.read(min(remaining, HASH_CHUNK))
                        if not chunk:
                            break
                        digest.update(chunk)
                        remaining -= len(chunk)
                    if not remaining and digest.hexdigest() == previous['prefix_sha256']:
                        offset, malformed = previous['offset'], previous['malformed']
                        seen = set(previous['seen'])
                    else:
                        stream.seek(0)
                        digest = hashlib.sha256()
                seen, malformed, partial, offset, digest = _scan(stream, seen, malformed, offset, digest)
                after = os.fstat(stream.fileno())
            # Do not publish a checkpoint from a transcript changing during scan.
            if _file_version(before) != _file_version(after) or _file_version(after) != _file_version(transcript.stat()):
                return count_compactions(transcript)
            current = {'schema': CACHE_SCHEMA, 'device': after.st_dev, 'inode': after.st_ino,
                       'offset': offset, 'prefix_sha256': digest.hexdigest(),
                       'seen': sorted(seen), 'malformed': malformed}
            if current != previous:
                current['checksum'] = _checksum(current)
                try:
                    _atomic_json(cache, current)
                except OSError:
                    pass  # The observed count is useful even without a writable cache.
            return len(seen), malformed, partial
    except (OSError, ValueError, TypeError):
        return count_compactions(transcript)


def _claim_notice(state_dir, thread_id, bucket, count):
    if state_dir is None:
        return True  # Diagnostics without writable state still report the count.
    state_dir = Path(state_dir)
    name = hashlib.sha256(thread_id.encode()).hexdigest()[:24]
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with _private_lock(state_dir / (name + '.notice.lock')):
            state = state_dir / (name + '.json')  # Preserve old notice receipt names.
            try:
                previous = json.loads(state.read_text(encoding='utf-8'))
                previous = previous if isinstance(previous, dict) else {}
                old_bucket = previous.get('last_notice_bucket', 0)
                if type(old_bucket) is not int or old_bucket < 0 or previous.get('thread_id') != thread_id:
                    old_bucket = 0
            except (OSError, ValueError, TypeError, RecursionError):
                old_bucket = 0
            if bucket <= old_bucket:
                try:
                    os.chmod(state, 0o600)
                except OSError:
                    pass  # Permission repair failure must not repeat a known notice.
                return False
            _atomic_json(state, {'thread_id': thread_id, 'last_notice_bucket': bucket,
                                 'observed_compactions': count})
            return True
    except BlockingIOError:
        # Another caller is claiming the notice; never wait or display a duplicate.
        return False
    except (OSError, ValueError, TypeError):
        # An advisory must not vanish just because notice/cache state is read-only.
        return True


def find_transcript(codex_home, thread_id):
    # Never fall back to the most recent task or scan another task's contents.
    if not thread_id or any(c not in '0123456789abcdef-' for c in thread_id.lower()):
        return None
    candidates = list((codex_home / 'sessions').glob('**/*-' + thread_id + '.jsonl'))
    if len(candidates) == 1:
        return candidates[0]
    return None


def advisory(transcript, thread_id, threshold=2, state_dir=None, claim=False):
    use_cache = state_dir is not None and Path(transcript).stat().st_size >= CACHE_MIN_BYTES
    count, malformed, partial = (_cached_count(transcript, thread_id, state_dir)
                                 if use_cache else count_compactions(transcript))
    result = {'status': 'partial' if malformed else 'ok',
              'thread_id': thread_id, 'observed_compactions': count,
              'threshold': threshold, 'remind': False,
              'malformed_lines': malformed, 'partial_tail': partial,
              'adapter': 'codex-jsonl-compacted-v1'}
    if count < threshold:
        return result
    bucket = count // threshold
    if claim and not _claim_notice(state_dir, thread_id, bucket, count):
        return result
    result['remind'] = True
    qualifier = '至少' if malformed else ''
    result['message'] = ('当前任务的本地日志已确认%s记录 %d 次上下文压缩。若需要换一个新任务继续，'
                         '可直接选择 handoff 技能或发送 $handoff，在同一 Local 项目开启新对话续接。当前工作继续。' % (qualifier, count))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--thread', default=os.environ.get('CODEX_THREAD_ID'))
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    parser.add_argument('--transcript', help='Explicit transcript path for diagnostics/testing')
    parser.add_argument('--state-dir', help='Optional per-task scan cache and notice receipt directory')
    parser.add_argument('--threshold', type=int, default=2)
    parser.add_argument('--claim-notice', action='store_true', help='Deduplicate this advisory for this task')
    args = parser.parse_args()
    try:
        home = Path(args.codex_home).expanduser()
        if not args.thread or args.threshold < 1:
            raise ValueError('A real current task ID and a positive threshold are required')
        path = Path(args.transcript) if args.transcript else find_transcript(home, args.thread)
        if path is None or not path.is_file():
            result = {'status': 'unavailable', 'remind': False,
                      'reason': 'Current task JSONL not uniquely available; no inferred count'}
        else:
            state_dir = args.state_dir or (home / 'handoff-state' if args.claim_notice else None)
            result = advisory(path, args.thread, args.threshold, state_dir, args.claim_notice)
    except Exception as exc:
        # Advisory failure must not interrupt normal work or request another turn.
        result = {'status': 'unavailable', 'remind': False,
                  'reason': type(exc).__name__ + ': ' + str(exc)[:180]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
