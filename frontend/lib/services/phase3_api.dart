import 'package:threadbot/models/phase3.dart';
import 'autonomy_api.dart';

class Phase3ApiService {
  final AutonomyApiService api;
  const Phase3ApiService(this.api);
  Future<dynamic> _request(String method, String path, {Object? body}) =>
      api.request(method, path, body: body);
  Future<CursorPage<HandoffContract>> contracts({
    String? cursor,
    int limit = 50,
  }) async {
    final j = await _request(
      'GET',
      '/api/handoff-contracts?limit=$limit${cursor == null ? '' : '&cursor=${Uri.encodeQueryComponent(cursor)}'}',
    );
    return CursorPage(
      ((j['items'] as List?) ?? const [])
          .map((x) => HandoffContract.fromJson(Map<String, dynamic>.from(x)))
          .toList(),
      j['next_cursor']?.toString(),
    );
  }

  Future<HandoffContract> contract(String id) => _request(
    'GET',
    '/api/handoff-contracts/$id',
  ).then((x) => HandoffContract.fromJson(Map<String, dynamic>.from(x)));
  Future<HandoffContract> createContract(Map<String, dynamic> body) => _request(
    'POST',
    '/api/handoff-contracts',
    body: body,
  ).then((x) => HandoffContract.fromJson(Map<String, dynamic>.from(x)));
  Future<Map<String, dynamic>> validateContract(
    String id,
    Map<String, dynamic> inputPayload,
  ) => _request(
    'POST',
    '/api/handoff-contracts/$id/validate',
    body: {'input_payload': inputPayload},
  ).then((x) => Map<String, dynamic>.from(x));
  Future<HandoffContract> patchContract(String id, Map<String, dynamic> body) =>
      _request(
        'PATCH',
        '/api/handoff-contracts/$id',
        body: body,
      ).then((x) => HandoffContract.fromJson(Map<String, dynamic>.from(x)));
  Future<HandoffContract> activateContract(String id) => _request(
    'POST',
    '/api/handoff-contracts/$id/activate',
  ).then((x) => HandoffContract.fromJson(Map<String, dynamic>.from(x)));
  Future<HandoffContract> archiveContract(String id) => _request(
    'POST',
    '/api/handoff-contracts/$id/archive',
  ).then((x) => HandoffContract.fromJson(Map<String, dynamic>.from(x)));
  Future<List<HandoffContract>> contractVersions(String id) =>
      _request('GET', '/api/handoff-contracts/$id/versions').then(
        (x) => (x as List)
            .map((v) => HandoffContract.fromJson(Map<String, dynamic>.from(v)))
            .toList(),
      );

  Future<CursorPage<AgentHandoff>> handoffs({
    String? cursor,
    int limit = 50,
  }) async {
    final j = await _request(
      'GET',
      '/api/handoffs?limit=$limit${cursor == null ? '' : '&cursor=${Uri.encodeQueryComponent(cursor)}'}',
    );
    return CursorPage(
      ((j['items'] as List?) ?? const [])
          .map((x) => AgentHandoff.fromJson(Map<String, dynamic>.from(x)))
          .toList(),
      j['next_cursor']?.toString(),
    );
  }

  Future<AgentHandoff> handoff(String id) => _request(
    'GET',
    '/api/handoffs/$id',
  ).then((x) => AgentHandoff.fromJson(Map<String, dynamic>.from(x)));
  Future<Map<String, dynamic>> acknowledge(String id) => _request(
    'POST',
    '/api/handoffs/$id/acknowledge',
  ).then((x) => Map<String, dynamic>.from(x));
  Future<List<PolicyRecommendation>> recommendations() =>
      _request('GET', '/api/policy-recommendations').then(
        (x) => (x as List)
            .map(
              (v) =>
                  PolicyRecommendation.fromJson(Map<String, dynamic>.from(v)),
            )
            .toList(),
      );
  Future<SlaStatus> sla(String id) => _request(
    'GET',
    '/api/handoffs/$id/sla',
  ).then((x) => SlaStatus.fromJson(Map<String, dynamic>.from(x)));
  Future<CursorPage<SlaIncident>> slaIncidents({
    String? cursor,
    int limit = 50,
  }) async {
    final j = await _request(
      'GET',
      '/api/sla-incidents?limit=$limit${cursor == null ? '' : '&cursor=${Uri.encodeQueryComponent(cursor)}'}',
    );
    return CursorPage(
      ((j['items'] as List?) ?? const [])
          .map((x) => SlaIncident.fromJson(Map<String, dynamic>.from(x)))
          .toList(),
      j['next_cursor']?.toString(),
    );
  }

  Future<CursorPage<Artifact>> artifacts({
    String? cursor,
    String? runId,
    int limit = 50,
  }) async {
    final j = await _request(
      'GET',
      '/api/artifacts?limit=$limit${cursor == null ? '' : '&cursor=${Uri.encodeQueryComponent(cursor)}'}${runId == null ? '' : '&run_id=${Uri.encodeQueryComponent(runId)}'}',
    );
    return CursorPage(
      ((j['items'] as List?) ?? const [])
          .map((x) => Artifact.fromJson(Map<String, dynamic>.from(x)))
          .toList(),
      j['next_cursor']?.toString(),
    );
  }

  Future<Artifact> setLegalHold(String id, bool hold) => _request(
    hold ? 'POST' : 'DELETE',
    '/api/artifacts/$id/legal-hold',
  ).then((x) => Artifact.fromJson(Map<String, dynamic>.from(x)));
  Future<Artifact> setRetention(String id, DateTime until) => _request(
    'PATCH',
    '/api/artifacts/$id/retention?retention_until=${Uri.encodeQueryComponent(until.toUtc().toIso8601String())}',
  ).then((x) => Artifact.fromJson(Map<String, dynamic>.from(x)));
  Future<List<ArtifactTombstone>> tombstones({int limit = 50}) =>
      _request('GET', '/api/artifact-tombstones?limit=$limit').then(
        (x) => ((x as List?) ?? const [])
            .map(
              (v) => ArtifactTombstone.fromJson(Map<String, dynamic>.from(v)),
            )
            .toList(),
      );
  Future<OperationsSummary> operationsSummary() => _request(
    'GET',
    '/api/operations/summary',
  ).then((x) => OperationsSummary.fromJson(Map<String, dynamic>.from(x)));
  Future<PolicyRecommendation> decideRecommendation(
    String id, {
    required bool accept,
  }) => _request(
    'POST',
    '/api/policy-recommendations/$id/decision',
    body: {'accept': accept},
  ).then((x) => PolicyRecommendation.fromJson(Map<String, dynamic>.from(x)));
}
