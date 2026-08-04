import 'package:flutter/foundation.dart';

String _text(Object? value) => value?.toString() ?? '';
Map<String, dynamic> _map(Object? value) => value is Map
    ? redactMap(Map<String, dynamic>.from(value))
    : <String, dynamic>{};
List<Map<String, dynamic>> _maps(Object? value) => value is List
    ? value.whereType<Map>().map((x) => _map(x)).toList()
    : <Map<String, dynamic>>[];
final _sensitiveValue = RegExp(
  r'(bearer\s+\S+|https?://[^\s/@]+:[^\s/@]+@|(?:token|secret|password|api[_-]?key)\s*[:=]\s*\S+)',
  caseSensitive: false,
);

bool _blocked(String key) {
  final k = key.toLowerCase().replaceAll('-', '_');
  return k.contains('secret') ||
      k.contains('password') ||
      k.contains('token') ||
      k.contains('api_key') ||
      k.contains('credential') ||
      k.contains('authorization') ||
      k.contains('cookie') ||
      k.contains('chain_of_thought') ||
      k.contains('hidden_reasoning') ||
      k == 'reasoning' ||
      k == 'thoughts';
}

dynamic redactValue(dynamic value) {
  if (value is Map) return redactMap(Map<String, dynamic>.from(value));
  if (value is List) return value.map(redactValue).toList();
  if (value is String && _sensitiveValue.hasMatch(value)) return '[REDACTED]';
  return value;
}

Map<String, dynamic> redactMap(Map<String, dynamic> value) => {
  for (final entry in value.entries)
    if (!_blocked(entry.key)) entry.key: redactValue(entry.value),
};

@immutable
class ReplaySession {
  final String id, mode, sourceRunId;
  final String? replayRunId;
  final bool effectFree;
  final List<Map<String, dynamic>> timeline;
  final Map<String, dynamic> comparison;
  const ReplaySession({
    this.id = '',
    this.mode = 'recorded',
    this.sourceRunId = '',
    this.replayRunId,
    this.effectFree = true,
    this.timeline = const [],
    this.comparison = const {},
  });
  factory ReplaySession.fromJson(Map<String, dynamic> json) => ReplaySession(
    id: _text(json['id']),
    mode: _text(json['mode']),
    sourceRunId: _text(json['source_run_id']),
    replayRunId: json['replay_run_id']?.toString(),
    effectFree: json['effect_free'] != false,
    timeline: _maps(json['timeline']),
    comparison: _map(json['comparison']),
  );
}

@immutable
class CanaryDeployment {
  final String id, status, stableVersionId, candidateVersionId;
  final int version;
  final Map<String, dynamic> cohort;
  const CanaryDeployment({
    this.id = '',
    this.status = 'unknown',
    this.stableVersionId = '',
    this.candidateVersionId = '',
    this.version = 1,
    this.cohort = const {},
  });
  factory CanaryDeployment.fromJson(Map<String, dynamic> json) =>
      CanaryDeployment(
        id: _text(json['id']),
        status: _text(json['status']),
        stableVersionId: _text(json['stable_version_id']),
        candidateVersionId: _text(json['candidate_version_id']),
        version: (json['version'] as num?)?.toInt() ?? 1,
        cohort: _map(json['cohort']),
      );
}

@immutable
class CanaryDecisionResponse {
  final String id, status, activeVersionId;
  const CanaryDecisionResponse({
    this.id = '',
    this.status = 'unknown',
    this.activeVersionId = '',
  });
  factory CanaryDecisionResponse.fromJson(Map<String, dynamic> json) =>
      CanaryDecisionResponse(
        id: _text(json['id']),
        status: _text(json['status']),
        activeVersionId: _text(json['active_version_id']),
      );
}

@immutable
class ForecastSnapshot {
  final int horizonHours;
  final Map<String, Map<String, num?>> metrics;
  final List<String> assumptions;
  final String confidence;
  const ForecastSnapshot({
    this.horizonHours = 24,
    this.metrics = const {},
    this.assumptions = const [],
    this.confidence = 'low',
  });
  factory ForecastSnapshot.fromJson(Map<String, dynamic> json) {
    final raw = json['metrics'] is Map ? json['metrics'] as Map : const {};
    return ForecastSnapshot(
      horizonHours: (json['horizon_hours'] as num?)?.toInt() ?? 24,
      metrics: {
        for (final entry in raw.entries)
          entry.key.toString(): entry.value is Map
              ? {
                  for (final x in (entry.value as Map).entries)
                    x.key.toString(): x.value is num ? x.value as num : null,
                }
              : <String, num?>{},
      },
      assumptions:
          (json['assumptions'] as List?)?.map(_text).toList() ?? const [],
      confidence: _text(json['confidence']),
    );
  }
}

@immutable
class SloSnapshot {
  final int runsTotal, queueDepth, deadLetters;
  final Map<String, dynamic> slo, metrics;
  final List<String> alerts;
  const SloSnapshot({
    this.runsTotal = 0,
    this.queueDepth = 0,
    this.deadLetters = 0,
    this.slo = const {},
    this.metrics = const {},
    this.alerts = const [],
  });
  factory SloSnapshot.fromJson(Map<String, dynamic> json) => SloSnapshot(
    runsTotal: (json['runs_total'] as num?)?.toInt() ?? 0,
    queueDepth: (json['queue_depth'] as num?)?.toInt() ?? 0,
    deadLetters: (json['dead_letters'] as num?)?.toInt() ?? 0,
    slo: _map(json['slo']),
    metrics: _map(json['metrics']),
    alerts: (json['alerts'] as List?)?.whereType<String>().toList() ?? const [],
  );
}
