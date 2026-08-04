import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:threadbot/models/autonomy.dart';
import 'http_client.dart';

class ApiException implements Exception {
  final int status;
  final String message;
  final Map<String, dynamic> body;
  const ApiException(this.status, this.message, [this.body = const {}]);
  bool get unauthorized => status == 401;
  bool get conflict => status == 409;
  @override
  String toString() => message;
}

class CursorPage<T> {
  final List<T> items;
  final String? nextCursor;
  const CursorPage(this.items, this.nextCursor);
}

class AgentRunRequest {
  final String message;
  final String mode;
  final String responseMode;
  const AgentRunRequest({
    required this.message,
    this.mode = 'live',
    this.responseMode = 'both',
  });

  Map<String, dynamic> toJson() => {
    'message': message,
    'mode': mode,
    'response_mode': responseMode,
  };
}

class AutonomyApiService {
  static String newIdempotencyKey() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    return bytes.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  }

  final String baseUrl;
  final http.Client client;
  final Map<String, String> Function()? headers;
  final VoidCallback? onUnauthorized;
  AutonomyApiService({
    String? baseUrl,
    http.Client? client,
    this.headers,
    this.onUnauthorized,
  }) : baseUrl =
           baseUrl ?? (kIsWeb ? Uri.base.origin : 'http://localhost:8000'),
       client = client ?? createHttpClient();
  Uri websocketUri(String path, {Map<String, String>? query}) {
    final base = Uri.parse(baseUrl);
    return base.replace(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      path: path,
      queryParameters: query,
    );
  }

  Future<dynamic> _request(
    String method,
    String path, {
    Object? body,
    Map<String, String>? extra,
  }) async {
    final h = {
      'Accept': 'application/json',
      if (body != null) 'Content-Type': 'application/json',
      ...?headers?.call(),
      ...?extra,
    };
    final req = http.Request(method, Uri.parse('$baseUrl$path'))
      ..headers.addAll(h);
    if (body != null) req.body = jsonEncode(body);
    final response = await client.send(req);
    final text = await response.stream.bytesToString();
    dynamic decoded;
    if (text.isNotEmpty) {
      try {
        decoded = jsonDecode(text);
      } catch (_) {
        decoded = text;
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      if (response.statusCode == 401) onUnauthorized?.call();
      throw ApiException(
        response.statusCode,
        decoded is Map
            ? (_string(decoded['detail']) ?? 'Request failed')
            : 'Request failed',
        decoded is Map ? Map<String, dynamic>.from(decoded) : {},
      );
    }
    return decoded;
  }

  Future<dynamic> request(
    String method,
    String path, {
    Object? body,
    Map<String, String>? extra,
  }) => _request(method, path, body: body, extra: extra);

  String? _string(Object? x) => x?.toString();
  Future<CursorPage<Agent>> agents({
    String? cursor,
    int limit = 50,
    String? query,
    String? status,
    bool? moderator,
    String? threadId,
  }) async {
    final params = <String, String>{'limit': '$limit'};
    if (cursor != null) params['cursor'] = cursor;
    if (query?.trim().isNotEmpty == true) params['q'] = query!.trim();
    if (status != null && status != 'all') params['status'] = status;
    if (moderator != null) params['moderator'] = '$moderator';
    if (threadId?.isNotEmpty == true) params['thread_id'] = threadId!;
    final j = await _request(
      'GET',
      Uri(path: '/api/autonomy/agents', queryParameters: params).toString(),
    );
    return CursorPage(
      ((j['items'] as List?) ?? const [])
          .map((x) => Agent.fromJson(Map<String, dynamic>.from(x)))
          .toList(),
      j['next_cursor']?.toString(),
    );
  }

  Future<Agent> agent(String id) => _request(
    'GET',
    '/api/autonomy/agents/$id',
  ).then((j) => Agent.fromJson(Map<String, dynamic>.from(j)));
  Future<Agent> createAgent(Map<String, dynamic> body) => _request(
    'POST',
    '/api/autonomy/agents',
    body: body,
  ).then((j) => Agent.fromJson(Map<String, dynamic>.from(j)));
  Future<Agent> patchAgent(String id, Map<String, dynamic> body) => _request(
    'PATCH',
    '/api/autonomy/agents/$id',
    body: body,
  ).then((j) => Agent.fromJson(Map<String, dynamic>.from(j)));
  Future<Agent> lifecycle(String id, bool active) => _request(
    'POST',
    '/api/autonomy/agents/$id/${active ? 'resume' : 'pause'}',
  ).then((j) => Agent.fromJson(Map<String, dynamic>.from(j)));
  Future<Draft> draft(String id) => _request(
    'GET',
    '/api/autonomy/agents/$id/draft',
  ).then((j) => Draft.fromJson(Map<String, dynamic>.from(j)));
  Future<Draft> saveDraft(String id, Map<String, dynamic> body) => _request(
    'PUT',
    '/api/autonomy/agents/$id/draft',
    body: body,
  ).then((j) => Draft.fromJson(Map<String, dynamic>.from(j)));
  Future<Version> activate(String id) => _request(
    'POST',
    '/api/autonomy/agents/$id/activate',
  ).then((j) => Version.fromJson(Map<String, dynamic>.from(j)));
  Future<List<Version>> versions(String id) =>
      _request('GET', '/api/autonomy/agents/$id/versions').then(
        (j) => (j as List)
            .map((x) => Version.fromJson(Map<String, dynamic>.from(x)))
            .toList(),
      );
  Future<List<Trigger>> triggers(String id) =>
      _request('GET', '/api/autonomy/agents/$id/triggers').then(
        (j) => (j as List)
            .map((x) => Trigger.fromJson(Map<String, dynamic>.from(x)))
            .toList(),
      );
  Future<Trigger> createTrigger(String id, Map<String, dynamic> body) =>
      _request(
        'POST',
        '/api/autonomy/agents/$id/triggers',
        body: body,
      ).then((j) => Trigger.fromJson(Map<String, dynamic>.from(j)));
  Future<Trigger> patchTrigger(String id, Map<String, dynamic> body) =>
      _request(
        'PATCH',
        '/api/autonomy/triggers/$id',
        body: body,
      ).then((j) => Trigger.fromJson(Map<String, dynamic>.from(j)));
  Future<void> deleteTrigger(String id) =>
      _request('DELETE', '/api/autonomy/triggers/$id').then((_) {});
  Future<void> pauseTriggerSchedule(String id) => _request(
    'POST',
    '/api/autonomy/triggers/$id/schedule/pause',
  ).then((_) {});
  Future<void> resumeTriggerSchedule(String id) => _request(
    'POST',
    '/api/autonomy/triggers/$id/schedule/resume',
  ).then((_) {});
  Future<Map<String, dynamic>> registerTriggerSchedule(String id) => _request(
    'POST',
    '/api/autonomy/triggers/$id/schedule',
  ).then((j) => Map<String, dynamic>.from(j));
  Future<Map<String, dynamic>> previewSchedule(
    String cron,
    String timezone, {
    int count = 5,
  }) => _request(
    'POST',
    '/api/autonomy/triggers/preview',
    body: {'cron': cron, 'timezone': timezone, 'count': count},
  ).then((j) => Map<String, dynamic>.from(j));
  Future<List<Map<String, dynamic>>> templates() => _request(
    'GET',
    '/api/autonomy/templates',
  ).then((j) => (j as List).map((x) => Map<String, dynamic>.from(x)).toList());
  Future<Run> run(
    String id,
    String message, {
    bool dryRun = false,
    required String idempotencyKey,
  }) => _request(
    'POST',
    '/api/autonomy/agents/$id/${dryRun ? 'dry-run' : 'run'}',
    body: {'message': message, 'mode': dryRun ? 'dry_run' : 'live'},
    extra: {'Idempotency-Key': idempotencyKey},
  ).then((j) => Run.fromJson(Map<String, dynamic>.from(j)));

  Future<Run> runThread(
    String threadId,
    AgentRunRequest request, {
    required String idempotencyKey,
  }) => _request(
    'POST',
    '/api/threads/$threadId/agent/run',
    body: request.toJson(),
    extra: {'Idempotency-Key': idempotencyKey},
  ).then((j) => Run.fromJson(Map<String, dynamic>.from(j)));
  Future<CursorPage<Run>> runs(String id, {String? cursor}) async {
    final j = await _request(
      'GET',
      '/api/autonomy/agents/$id/runs?limit=50${cursor == null ? '' : '&after=${Uri.encodeQueryComponent(cursor)}'}',
    );
    return CursorPage(
      ((j['items'] as List?) ?? const [])
          .map((x) => Run.fromJson(Map<String, dynamic>.from(x)))
          .toList(),
      j['next_cursor']?.toString(),
    );
  }

  Future<Run> runDetail(String id) => _request(
    'GET',
    '/api/autonomy/runs/$id',
  ).then((j) => Run.fromJson(Map<String, dynamic>.from(j)));
  Future<CursorPage<RunEvent>> events(String id, {int after = 0}) async {
    final j = await _request(
      'GET',
      '/api/autonomy/runs/$id/events?after=$after',
    );
    return CursorPage(
      ((j['items'] as List?) ?? const [])
          .map((x) => RunEvent.fromJson(Map<String, dynamic>.from(x)))
          .toList(),
      j['next_cursor']?.toString(),
    );
  }

  Future<Run> cancel(String id) => _request(
    'POST',
    '/api/autonomy/runs/$id/cancel',
  ).then((j) => Run.fromJson(Map<String, dynamic>.from(j)));
  Future<CursorPage<AuditEntry>> audit({String? cursor}) async {
    final j = await _request(
      'GET',
      '/api/autonomy/audit-events?limit=50${cursor == null ? '' : '&after=${Uri.encodeQueryComponent(cursor)}'}',
    );
    return CursorPage(
      ((j['items'] as List?) ?? const [])
          .map((x) => AuditEntry.fromJson(Map<String, dynamic>.from(x)))
          .toList(),
      j['next_cursor']?.toString(),
    );
  }

  Future<void> createSession(String token) async {
    await _request(
      'POST',
      '/api/auth/session',
      extra: {'Authorization': 'Bearer $token'},
    );
  }

  Future<Map<String, dynamic>> capabilities() => _request(
    'GET',
    '/api/autonomy/capabilities',
  ).then((j) => Map<String, dynamic>.from(j));

  // ---- Adaptive heartbeat -------------------------------------------------

  Future<HeartbeatStatus> heartbeat(String agentId) => _request(
    'GET',
    '/api/autonomy/agents/$agentId/heartbeat',
  ).then((j) => HeartbeatStatus.fromJson(Map<String, dynamic>.from(j)));

  Future<HeartbeatStatus> updateHeartbeat(
    String agentId,
    HeartbeatConfig config,
  ) => _request(
    'PUT',
    '/api/autonomy/agents/$agentId/heartbeat',
    body: config.toJson(),
  ).then((j) => HeartbeatStatus.fromJson(Map<String, dynamic>.from(j)));

  Future<HeartbeatStatus> wakeHeartbeat(String agentId) => _request(
    'POST',
    '/api/autonomy/agents/$agentId/heartbeat/wake',
  ).then((j) => HeartbeatStatus.fromJson(Map<String, dynamic>.from(j)));
}
