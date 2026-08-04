import 'package:flutter/foundation.dart';

String _s(Object? v) => v?.toString() ?? '';
Map<String, dynamic> _m(Object? v) =>
    v is Map ? Map<String, dynamic>.from(v) : {};
DateTime? _d(Object? v) => DateTime.tryParse(_s(v))?.toUtc();
Map<String, dynamic> _safe(Map<String, dynamic> value) {
  const hidden = {'secret', 'token', 'password', 'api_key', 'ciphertext'};
  return Map<String, dynamic>.unmodifiable({
    for (final entry in value.entries)
      if (!hidden.contains(entry.key.toLowerCase())) entry.key: entry.value,
  });
}

@immutable
class Phase2Record {
  final String id;
  final Map<String, dynamic> data;
  const Phase2Record(this.id, this.data);
  factory Phase2Record.fromJson(Map<String, dynamic> j) =>
      Phase2Record(_s(j['id']), _safe(j));
  String get name => _s(data['name']);
  String get status => _s(data['status']);
  String get type =>
      _s(data['connector_type'] ?? data['stage'] ?? data['event_type']);
  DateTime? get createdAt => _d(data['created_at']);
}

@immutable
class Approval {
  final String id, runId, actionId, status, riskLevel, requestHash;
  final Map<String, dynamic> target, arguments, explanation;
  final DateTime? expiresAt;
  bool get expired =>
      expiresAt != null && expiresAt!.isBefore(DateTime.now().toUtc());
  const Approval({
    required this.id,
    required this.runId,
    required this.actionId,
    required this.status,
    required this.riskLevel,
    required this.requestHash,
    this.target = const {},
    this.arguments = const {},
    this.explanation = const {},
    this.expiresAt,
  });
  factory Approval.fromJson(Map<String, dynamic> j) => Approval(
    id: _s(j['id']),
    runId: _s(j['run_id']),
    actionId: _s(j['action_id']),
    status: _s(j['status']),
    riskLevel: _s(j['risk_level']),
    requestHash: _s(j['request_hash']),
    target: _m(j['target']),
    arguments: _m(j['redacted_arguments']),
    explanation: _m(j['policy_explanation']),
    expiresAt: _d(j['expires_at']),
  );
}

@immutable
class Phase2Event {
  final int cursor;
  final String type;
  final Map<String, dynamic> payload;
  const Phase2Event(this.cursor, this.type, this.payload);
  factory Phase2Event.fromJson(Map<String, dynamic> j) => Phase2Event(
    int.tryParse(_s(j['cursor'] ?? j['sequence'])) ?? 0,
    _s(j['event_type'] ?? j['type']),
    _m(j['payload']),
  );
}
