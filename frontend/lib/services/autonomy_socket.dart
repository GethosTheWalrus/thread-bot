import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';

class EventCursorBuffer<T> {
  int cursor;
  final List<T> values = [];
  final T Function(Map<String, dynamic>) decode;
  EventCursorBuffer({this.cursor = 0, required this.decode});
  bool add(Map<String, dynamic> json, int valueCursor) {
    if (valueCursor <= cursor) return false;
    if (valueCursor > cursor + 1) {
      return false;
    }
    cursor = valueCursor;
    values.add(decode(json));
    return true;
  }
}

class AutonomySocket<T> {
  final Uri Function(int after) uriBuilder;
  final T Function(Map<String, dynamic>) decode;
  final Future<int> Function(int after)? onGap;
  final bool strictSequence;
  final _events = StreamController<T>.broadcast();
  WebSocketChannel? _channel;
  Timer? _retry;
  bool _disposed = false;
  bool _recovering = false;
  int cursor;
  int _attempt = 0;
  int _gapAttempts = 0;
  int _connectionGeneration = 0;
  AutonomySocket({
    required this.uriBuilder,
    required this.decode,
    this.onGap,
    this.cursor = 0,
    this.strictSequence = true,
  });
  Stream<T> get stream => _events.stream;
  void connect() {
    if (_disposed) return;
    _retry?.cancel();
    try {
      final generation = ++_connectionGeneration;
      _channel = WebSocketChannel.connect(uriBuilder(cursor));
      _attempt = 0;
      _channel!.stream.listen(
        (raw) => _receive(raw, generation),
        onError: (_) => _schedule(),
        onDone: _schedule,
      );
    } catch (_) {
      _schedule();
    }
  }

  void _receive(dynamic raw, int generation) {
    if (generation != _connectionGeneration) return;
    try {
      final text = raw is String ? raw : utf8.decode(raw as List<int>);
      final j = Map<String, dynamic>.from(jsonDecode(text));
      final c = (j['sequence'] ?? j['cursor']);
      final next = c is num ? c.toInt() : int.tryParse('$c') ?? 0;
      if (next <= cursor) return;
      if (strictSequence && next > cursor + 1) {
        _recoverGap(next);
        return;
      }
      _gapAttempts = 0;
      cursor = next;
      _events.add(decode(j));
    } catch (_) {}
  }

  Future<void> _recoverGap(int next) async {
    if (_disposed || onGap == null || _recovering) return;
    _recovering = true;
    try {
      final latest = await onGap!(cursor);
      if (_disposed) return;
      if (latest > cursor) {
        cursor = latest;
        _gapAttempts = 0;
      } else if (++_gapAttempts >= 3) {
        // Resume immediately before the observed event when older events were
        // pruned or otherwise cannot be recovered.
        cursor = next - 1;
        _gapAttempts = 0;
      }
      await _channel?.sink.close();
      _schedule();
    } finally {
      _recovering = false;
    }
  }

  void _schedule() {
    if (_disposed || _retry?.isActive == true) return;
    final delay = Duration(milliseconds: 250 * (1 << (_attempt++).clamp(0, 5)));
    _retry = Timer(delay, connect);
  }

  Future<void> dispose() async {
    _disposed = true;
    _retry?.cancel();
    await _channel?.sink.close();
    await _events.close();
  }
}
