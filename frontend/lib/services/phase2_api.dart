import 'package:threadbot/models/phase2.dart';
import 'autonomy_api.dart';

class Phase2ApiService {
  final AutonomyApiService api;
  const Phase2ApiService(this.api);
  Map<String, String> _key() => {
    'Idempotency-Key': AutonomyApiService.newIdempotencyKey(),
  };
  Future<dynamic> _get(
    String method,
    String path, {
    Object? body,
    Map<String, String>? extra,
  }) => api.request(method, path, body: body, extra: extra);
  Future<List<Phase2Record>> _list(String path) async {
    final value = await _get('GET', path);
    final list = value is List
        ? value
        : ((value as Map?)?['items'] as List? ?? const []);
    return list
        .map((x) => Phase2Record.fromJson(Map<String, dynamic>.from(x)))
        .toList();
  }

  Future<List<Phase2Record>> connectors() => _list('/api/connectors');
  Future<Phase2Record> createConnector(Map<String, dynamic> body) => _get(
    'POST',
    '/api/connectors',
    body: body,
    extra: _key(),
  ).then((x) => Phase2Record.fromJson(Map<String, dynamic>.from(x)));
  Future<void> deleteConnector(String id) =>
      _get('DELETE', '/api/connectors/$id').then((_) {});
  Future<Phase2Record> patchConnector(String id, Map<String, dynamic> body) =>
      _get(
        'PATCH',
        '/api/connectors/$id',
        body: body,
        extra: _key(),
      ).then((x) => Phase2Record.fromJson(Map<String, dynamic>.from(x)));
  Future<List<Phase2Record>> credentials() => _list('/api/credentials');
  Future<Phase2Record> createCredential(
    String name,
    String provider,
    String secret,
  ) => _get(
    'POST',
    '/api/credentials',
    body: {'name': name, 'provider': provider, 'secret': secret},
    extra: _key(),
  ).then((x) => Phase2Record.fromJson(Map<String, dynamic>.from(x)));
  Future<Phase2Record> rotateCredential(
    String id,
    String name,
    String provider,
    String secret,
  ) => _get(
    'POST',
    '/api/credentials/$id/rotate',
    body: {'name': name, 'provider': provider, 'secret': secret},
    extra: _key(),
  ).then((x) => Phase2Record.fromJson(Map<String, dynamic>.from(x)));
  Future<List<Phase2Record>> credentialVersions(String id) =>
      _list('/api/credentials/$id/versions');
  Future<void> deleteCredential(String id) =>
      _get('DELETE', '/api/credentials/$id').then((_) {});
  Future<List<Phase2Record>> bindings() => _list('/api/credential-bindings');
  Future<Phase2Record> createBinding(Map<String, dynamic> body) => _get(
    'POST',
    '/api/credential-bindings',
    body: body,
    extra: _key(),
  ).then((x) => Phase2Record.fromJson(Map<String, dynamic>.from(x)));
  Future<Map<String, dynamic>> explainPolicy(Map<String, dynamic> body) => _get(
    'POST',
    '/api/policies/explain',
    body: body,
  ).then((x) => Map<String, dynamic>.from(x));
  Future<List<Approval>> approvals({String? threadId}) =>
      _get(
        'GET',
        '/api/approvals${threadId == null ? '' : '?thread_id=${Uri.encodeQueryComponent(threadId)}'}',
      ).then(
        (x) => ((x is List ? x : (x as Map?)?['items']) as List? ?? const [])
            .map((v) => Approval.fromJson(Map<String, dynamic>.from(v)))
            .toList(),
      );
  Future<void> decide(String id, String decision, {String? reason}) => _get(
    'POST',
    '/api/approvals/$id/decision',
    body: {'decision': decision, if (reason != null) 'reason': reason},
    extra: _key(),
  ).then((_) {});
  Future<List<Phase2Record>> notificationProfiles() =>
      _list('/api/notifications/profiles');
  Future<Phase2Record> createNotificationProfile(Map<String, dynamic> body) =>
      _get(
        'POST',
        '/api/notifications/profiles',
        body: body,
        extra: _key(),
      ).then((x) => Phase2Record.fromJson(Map<String, dynamic>.from(x)));
  Future<List<Phase2Record>> notificationRoutes(String id) =>
      _list('/api/notifications/profiles/$id/routes');
  Future<Phase2Record> createNotificationRoute(
    String id,
    Map<String, dynamic> body,
  ) => _get(
    'POST',
    '/api/notifications/profiles/$id/routes',
    body: body,
    extra: _key(),
  ).then((x) => Phase2Record.fromJson(Map<String, dynamic>.from(x)));
  Future<List<Phase2Record>> deadLetters() => _list('/api/dead-letters');
  Future<void> retryDeadLetter(String id) =>
      _get('POST', '/api/dead-letters/$id/retry', extra: _key()).then((_) {});
  Future<Map<String, dynamic>> stateDiff(String id) => _get(
    'GET',
    '/api/runs/$id/state-diff',
  ).then((x) => Map<String, dynamic>.from(x));
  Future<List<Phase2Event>> workspaceEvents({int after = 0}) async {
    final x = await _get('GET', '/api/events?after=$after');
    return ((x['events'] as List?) ?? const [])
        .map((v) => Phase2Event.fromJson(Map<String, dynamic>.from(v)))
        .toList();
  }
}
