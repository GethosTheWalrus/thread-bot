import 'package:flutter_test/flutter_test.dart';
import 'package:threadbot/models/autonomy.dart';

void main() {
  group('HeartbeatStatus', () {
    test('parses default disabled state', () {
      final s = HeartbeatStatus.fromJson({'agent_id': 'a'});
      expect(s.enabled, isFalse);
      expect(s.operationalStatus, 'disabled');
      expect(s.minWakeSeconds, 300);
      expect(s.maxWakeSeconds, 3600);
      expect(s.idleBackoffFactor, 2.0);
      expect(s.consecutiveNoops, 0);
      expect(s.lastDecision, isNull);
      expect(s.statusLabel, 'Off');
    });

    test('parses enabled scheduled state with next wake', () {
      final s = HeartbeatStatus.fromJson({
        'agent_id': 'a',
        'enabled': true,
        'min_wake_seconds': 600,
        'max_wake_seconds': 7200,
        'idle_backoff_factor': 3.5,
        'revision': 4,
        'operational_status': 'scheduled',
        'next_wake_at': '2099-01-01T00:00:00Z',
        'last_decision': 'response',
        'consecutive_noops': 2,
      });
      expect(s.enabled, isTrue);
      expect(s.minWakeSeconds, 600);
      expect(s.maxWakeSeconds, 7200);
      expect(s.idleBackoffFactor, 3.5);
      expect(s.revision, 4);
      expect(s.operationalStatus, 'scheduled');
      expect(s.lastDecision, 'response');
      expect(s.consecutiveNoops, 2);
      expect(s.statusLabel, contains('Next wake'));
    });

    test('parses blocked/error states', () {
      expect(
        HeartbeatStatus.fromJson({
          'agent_id': 'a',
          'operational_status': 'blocked_global',
        }).statusLabel,
        'Blocked (autonomy disabled)',
      );
      expect(
        HeartbeatStatus.fromJson({
          'agent_id': 'a',
          'operational_status': 'error',
          'last_error': 'boom',
        }).statusLabel,
        'Error',
      );
      expect(
        HeartbeatStatus.fromJson({
          'agent_id': 'a',
          'operational_status': 'evaluating',
        }).statusLabel,
        'Evaluating',
      );
    });

    test('parses numeric backoff from string fallback', () {
      final s = HeartbeatStatus.fromJson({
        'agent_id': 'a',
        'idle_backoff_factor': '1.5',
      });
      expect(s.idleBackoffFactor, 1.5);
    });
  });

  group('HeartbeatConfig', () {
    test('serializes without expected_revision when null', () {
      final j = HeartbeatConfig(enabled: true).toJson();
      expect(j.containsKey('expected_revision'), isFalse);
      expect(j['enabled'], isTrue);
    });

    test('serializes with expected_revision when provided', () {
      final j = HeartbeatConfig(enabled: false, expectedRevision: 3).toJson();
      expect(j['expected_revision'], 3);
      expect(j['enabled'], isFalse);
    });
  });
}
