import 'package:threadbot/models/phase4.dart';
import 'package:threadbot/services/autonomy_api.dart';

class Phase4ApiService {
  final AutonomyApiService base;
  Phase4ApiService(this.base);

  Future<ReplaySession> replay(
    String runId, {
    required String mode,
    required String idempotencyKey,
  }) async => ReplaySession.fromJson(
    Map<String, dynamic>.from(
      await base.request(
        'POST',
        '/api/agent-runs/$runId/replay',
        body: {'mode': mode, 'dry_run': true},
        extra: {'Idempotency-Key': idempotencyKey},
      ),
    ),
  );
  Future<List<ReplaySession>> replays(String runId) async =>
      (await base.request('GET', '/api/agent-runs/$runId/replay') as List)
          .map((x) => ReplaySession.fromJson(Map<String, dynamic>.from(x)))
          .toList();
  Future<Map<String, dynamic>> exportReplay(String runId) async => redactMap(
    Map<String, dynamic>.from(
      await base.request('GET', '/api/agent-runs/$runId/replay/export'),
    ),
  );
  Future<CanaryDeployment> createCanary(
    String agentId,
    String versionId, {
    Map<String, dynamic> cohort = const {},
  }) async => CanaryDeployment.fromJson(
    Map<String, dynamic>.from(
      await base.request(
        'POST',
        '/api/agents/$agentId/canary',
        body: {'candidate_version_id': versionId, 'cohort': cohort},
      ),
    ),
  );
  Future<List<CanaryDeployment>> canaries(String agentId) async =>
      (await base.request('GET', '/api/agents/$agentId/canary') as List)
          .map((x) => CanaryDeployment.fromJson(Map<String, dynamic>.from(x)))
          .toList();
  Future<CanaryDecisionResponse> decideCanary(
    String id,
    String action, {
    required String reason,
    int? expectedVersion,
  }) async => CanaryDecisionResponse.fromJson(
    Map<String, dynamic>.from(
      await base.request(
        'POST',
        '/api/canaries/$id/$action',
        body: {
          'reason': reason,
          if (expectedVersion != null) 'expected_version': expectedVersion,
        },
      ),
    ),
  );
  Future<List<Map<String, dynamic>>> comparisons(String id) async =>
      (await base.request('GET', '/api/canaries/$id/comparisons') as List)
          .map((x) => redactMap(Map<String, dynamic>.from(x)))
          .toList();
  Future<ForecastSnapshot> forecast(
    String agentId, {
    int horizonHours = 24,
  }) async => ForecastSnapshot.fromJson(
    Map<String, dynamic>.from(
      await base.request(
        'GET',
        '/api/agents/$agentId/forecast?horizon_hours=$horizonHours',
      ),
    ),
  );
  Future<SloSnapshot> slo() async => SloSnapshot.fromJson(
    Map<String, dynamic>.from(await base.request('GET', '/api/operations/slo')),
  );
  Future<List<Map<String, dynamic>>> alerts() async =>
      (await base.request('GET', '/api/operations/alerts') as List)
          .map((x) => redactMap(Map<String, dynamic>.from(x)))
          .toList();
  Future<Map<String, dynamic>> recover(
    String operation,
    String resourceId, {
    Map<String, dynamic> details = const {},
  }) async => Map<String, dynamic>.from(
    await base.request(
      'POST',
      '/api/operations/recovery',
      body: {
        'operation': operation,
        'resource_id': resourceId,
        'details': redactMap(details),
      },
    ),
  );
  Future<Map<String, dynamic>> queueState(String queue, String state) async =>
      Map<String, dynamic>.from(
        await base.request(
          'POST',
          '/api/operations/queues/${Uri.encodeComponent(queue)}/$state',
        ),
      );
}
