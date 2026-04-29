import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/models/mcp_server.dart';
import 'package:flutter/foundation.dart'; // For kIsWeb

class ApiService {
  final String baseUrl;

  ApiService({String? baseUrl})
      : baseUrl = baseUrl ?? (kIsWeb ? Uri.base.origin : 'http://localhost:8000');

  // ── Threads ───────────────────────────────────────────────────────

  Future<List<ThreadListItem>> getThreads({int limit = 50, int offset = 0}) async {
    final response = await http.get(
      Uri.parse('$baseUrl/api/threads?limit=$limit&offset=$offset'),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final threads = (data['threads'] as List<dynamic>)
          .map((t) => ThreadListItem.fromJson(t as Map<String, dynamic>))
          .toList();
      return threads;
    }
    throw Exception('Failed to load threads: ${response.statusCode}');
  }

  Future<Thread> getThread(String threadId) async {
    final response = await http.get(
      Uri.parse('$baseUrl/api/threads/$threadId'),
    );

    if (response.statusCode == 200) {
      return Thread.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to load thread: ${response.statusCode}');
  }

  /// Send a message. If threadId is provided, appends to that thread.
  /// Otherwise creates a new thread.
  /// LLM config is managed server-side — no need to send it per request.
  Stream<String> sendMessageStream(String content, {String? threadId}) async* {
    final body = <String, dynamic>{
      'content': content,
    };

    if (threadId != null) body['thread_id'] = threadId;

    final request = http.Request('POST', Uri.parse('$baseUrl/api/chat'));
    request.headers['Content-Type'] = 'application/json';
    request.body = jsonEncode(body);

    final client = http.Client();
    try {
      final response = await client.send(request);
      if (response.statusCode != 200) {
        throw Exception('Failed to send message: ${response.statusCode}');
      }
      await for (final chunk in response.stream.transform(utf8.decoder)) {
        yield chunk;
      }
    } finally {
      client.close();
    }
  }

  /// Reconnect to an in-progress generation stream after page refresh.
  /// The backend replays all buffered events from the beginning.
  /// If the thread is not generating (204), the stream completes immediately.
  Stream<String> reconnectStream(String threadId) {
    return _reconnectStreamImpl(threadId);
  }

  Stream<String> _reconnectStreamImpl(String threadId) async* {
    final request = http.Request('GET', Uri.parse('$baseUrl/api/threads/$threadId/stream'));

    final client = http.Client();
    try {
      final response = await client.send(request);
      if (response.statusCode == 204) {
        // Not generating — no stream to reconnect to
        return;
      }
      if (response.statusCode != 200) {
        throw Exception('Failed to reconnect: ${response.statusCode}');
      }
      await for (final chunk in response.stream.transform(utf8.decoder)) {
        yield chunk;
      }
    } finally {
      client.close();
    }
  }

  Future<Thread> createThread({String title = 'New Thread'}) async {
    final response = await http.post(
      Uri.parse('$baseUrl/api/threads'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'title': title}),
    );

    if (response.statusCode == 200) {
      return Thread.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to create thread: ${response.statusCode}');
  }

  Future<void> deleteThread(String threadId) async {
    final response = await http.delete(
      Uri.parse('$baseUrl/api/threads/$threadId'),
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to delete thread: ${response.statusCode}');
    }
  }

  Future<void> deleteAllThreads() async {
    final response = await http.delete(
      Uri.parse('$baseUrl/api/threads'),
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to delete all threads: ${response.statusCode}');
    }
  }

  Future<Thread> renameThread(String threadId, String title) async {
    final response = await http.patch(
      Uri.parse('$baseUrl/api/threads/$threadId'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'title': title}),
    );

    if (response.statusCode == 200) {
      return Thread.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to rename thread: ${response.statusCode}');
  }

  // ── Settings ──────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getSettings() async {
    final response = await http.get(
      Uri.parse('$baseUrl/api/settings'),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to load settings: ${response.statusCode}');
  }

  Future<void> saveSettingsToBackend(Map<String, dynamic> settings) async {
    final response = await http.patch(
      Uri.parse('$baseUrl/api/settings'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(settings),
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to save settings: ${response.statusCode}');
    }
  }

  // ── MCP Servers ───────────────────────────────────────────────────

  Future<List<MCPServer>> getMCPServers() async {
    final response = await http.get(
      Uri.parse('$baseUrl/api/mcp'),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as List<dynamic>;
      return data.map((s) => MCPServer.fromJson(s as Map<String, dynamic>)).toList();
    }
    throw Exception('Failed to load MCP servers: ${response.statusCode}');
  }

  Future<MCPServer> createMCPServer({
    required String name,
    required String image,
    Map<String, dynamic>? envVars,
    Map<String, dynamic>? args,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/api/mcp'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'image': image,
        'env_vars': envVars ?? {},
        'args': args ?? {},
      }),
    );

    if (response.statusCode == 200) {
      return MCPServer.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to create MCP server: ${response.statusCode}');
  }

  Future<void> deleteMCPServer(String serverId) async {
    final response = await http.delete(
      Uri.parse('$baseUrl/api/mcp/$serverId'),
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to delete MCP server: ${response.statusCode}');
    }
  }

  Future<MCPServer> toggleMCPServer(String serverId) async {
    final response = await http.patch(
      Uri.parse('$baseUrl/api/mcp/$serverId/toggle'),
    );

    if (response.statusCode == 200) {
      return MCPServer.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to toggle MCP server: ${response.statusCode}');
  }

  Future<Map<String, dynamic>> testMCPServer(String serverId) async {
    final response = await http.post(
      Uri.parse('$baseUrl/api/mcp/$serverId/test'),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to test MCP server: ${response.statusCode}');
  }

  Future<MCPServer> updateMCPServer(String serverId, String name, String image, Map<String, String> envVars, {Map<String, String>? args}) async {
    final response = await http.patch(
      Uri.parse('$baseUrl/api/mcp/$serverId'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'image': image,
        'env_vars': envVars,
        'args': args ?? {},
      }),
    );

    if (response.statusCode == 200) {
      return MCPServer.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to update MCP server: ${response.statusCode}');
  }
}
