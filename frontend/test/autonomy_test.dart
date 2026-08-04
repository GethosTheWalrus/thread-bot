import 'package:flutter_test/flutter_test.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/services/autonomy_socket.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/models/phase2.dart';
import 'package:threadbot/models/phase3.dart';
import 'package:threadbot/models/phase4.dart';
import 'package:threadbot/models/thread.dart';

void main() {
  test('thread projections parse nested agent and active run shape', () {
    final thread = ThreadListItem.fromJson({
      'id': 'thread-1',
      'title': 'Work',
      'created_at': '2026-01-01T00:00:00Z',
      'updated_at': '2026-01-01T00:00:00Z',
      'mode': 'chat',
      'agent': {
        'id': 'agent-1',
        'name': 'Planner',
        'status': 'active',
        'execution_mode': 'interactive',
      },
      'latest_active_run': {'id': 'run-1', 'status': 'running', 'mode': 'live'},
      'pending_approvals': 2,
    });
    expect(thread.mode, 'chat');
    expect(thread.agent?.id, 'agent-1');
    expect(thread.latestActiveRun?.status, 'running');
    expect(thread.pendingApprovals, 2);
  });

  test('thread run request uses the typed scoped payload', () {
    final payload = AgentRunRequest(message: 'hello').toJson();
    expect(payload, {
      'message': 'hello',
      'mode': 'live',
      'response_mode': 'both',
    });
    expect(payload.containsKey('thread_id'), isFalse);
    expect(payload.containsKey('agent_id'), isFalse);
  });

  test('parses normalized audit fields and UTC dates', () {
    final entry = AuditEntry.fromJson({
      'id': 'a',
      'event_type': 'agent.updated',
      'resource_type': 'agent',
      'metadata': {'mode': 'dry_run'},
      'created_at': '2026-01-01T12:00:00+02:00',
    });
    expect(entry.type, 'agent.updated');
    expect(entry.metadata['mode'], 'dry_run');
    expect(entry.createdAt!.isUtc, isTrue);
  });

  test('event cursor deduplicates and rejects gaps', () {
    final buffer = EventCursorBuffer<int>(
      decode: (json) => json['value'] as int,
    );
    expect(buffer.add({'value': 1}, 1), isTrue);
    expect(buffer.add({'value': 1}, 1), isFalse);
    expect(buffer.add({'value': 3}, 3), isFalse);
    expect(buffer.values, [1]);
  });

  test('phase two models never expose credential secrets', () {
    final credential = Phase2Record.fromJson({
      'id': 'c',
      'name': 'prod',
      'has_secret': true,
    });
    expect(credential.data['secret'], isNull);
    final approval = Approval.fromJson({
      'id': 'a',
      'run_id': 'r',
      'action_id': 'x',
      'status': 'pending',
      'risk_level': 'high',
      'request_hash': 'h',
      'redacted_arguments': {'token': '[redacted]'},
    });
    expect(approval.arguments['token'], '[redacted]');
  });

  test('workspace cursor accepts monotonic gaps', () {
    final buffer = EventCursorBuffer<int>(
      decode: (json) => json['value'] as int,
    );
    expect(buffer.add({'value': 2}, 2), isFalse);
    expect(buffer.cursor, 0);
  });

  test('phase three models are typed and redact sensitive payload keys', () {
    final handoff = AgentHandoff.fromJson({
      'id': 'h',
      'contract_id': 'c',
      'source_run_id': 'r',
      'target_agent_id': 'a',
      'status': 'pending',
      'response_mode': 'async',
      'output_payload': {'result': 'ok', 'token': 'must not render'},
    });
    expect(handoff.active, isTrue);
    expect(handoff.outputPayload!['token'], isNull);
    final recommendation = PolicyRecommendation.fromJson({
      'id': 'p',
      'risk': 'medium',
      'status': 'pending',
      'evidence': {'count': 2},
      'proposed_diff': {'limit': 4},
    });
    expect(recommendation.proposedDiff['limit'], 4);
  });

  test('phase three operations models parse queue and retention state', () {
    final summary = OperationsSummary.fromJson({
      'active_runs': 2,
      'queued_runs': 3,
      'pending_handoffs': 1,
      'sla_incidents': 4,
      'queue_health': {'agent': 'threadbot-agent'},
    });
    expect(summary.queuedRuns, 3);
    expect(summary.queueHealth['agent'], 'threadbot-agent');
    final artifact = Artifact.fromJson({
      'id': 'a',
      'content_type': 'text/plain',
      'size_bytes': 10,
      'sha256': 'hash',
      'classification': 'internal',
      'legal_hold': 1,
      'retention_until': '2026-01-01T00:00:00Z',
    });
    expect(artifact.onLegalHold, isTrue);
  });

  test('phase four recursively redacts secrets and hidden reasoning', () {
    final replay = ReplaySession.fromJson({
      'mode': 'reexecution',
      'effect_free': true,
      'timeline': [
        {
          'summary': 'safe',
          'nested': {'api_key': 'secret', 'reasoning': 'private'},
        },
      ],
    });
    expect(replay.timeline.single['nested'], isEmpty);
    expect(replay.mode, 'reexecution');
  });

  test('phase four redaction protects secret-looking values too', () {
    final redacted = redactMap({
      'payload': 'Authorization: Bearer ciphertext-value',
      'safe': 'ordinary event summary',
      'nested': {'value': 'api_key=do-not-leak'},
    });
    expect(redacted['payload'], '[REDACTED]');
    expect((redacted['nested'] as Map)['value'], '[REDACTED]');
    expect(redacted['safe'], 'ordinary event summary');
  });

  test('phase four canary decisions parse typed version response', () {
    final response = CanaryDecisionResponse.fromJson({
      'id': 'deployment',
      'status': 'promoted',
      'active_version_id': 'version-2',
    });
    expect(response.status, 'promoted');
    expect(response.activeVersionId, 'version-2');
  });

  test('phase four forecast preserves P50/P90 metrics and assumptions', () {
    final forecast = ForecastSnapshot.fromJson({
      'horizon_hours': 48,
      'metrics': {
        'tokens': {'p50': 100, 'p90': 250},
      },
      'assumptions': ['observed runs'],
      'confidence': 'medium',
    });
    expect(forecast.horizonHours, 48);
    expect(forecast.metrics['tokens']!['p90'], 250);
    expect(forecast.assumptions, ['observed runs']);
  });
}
