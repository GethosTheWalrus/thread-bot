import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/models/mcp_server.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  final String baseUrl;

  ApiService({this.baseUrl = 'http://localhost:8000'});

  // ── LLM Settings (local storage) ──────────────────────────────────

  Future<String?> getLlmApiUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('llm_api_url');
  }

  Future<String?> getLlmApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('llm_api_key');
  }

  Future<String?> getLlmModel() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('llm_model');
  }

  Future<void> saveSettings({
    required String apiUrl,
    required String apiKey,
    required String model,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('llm_api_url', apiUrl);
    await prefs.setString('llm_api_key', apiKey);
    await prefs.setString('llm_model', model);
  }

  Future<void> sendSettingsToBackend({
    required String apiUrl,
    required String apiKey,
    required String model,
  }) async {
    try {
      await http.patch(
        Uri.parse('$baseUrl/api/settings'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'llm_api_url': apiUrl,
          'llm_api_key': apiKey,
          'llm_model': model,
        }),
      );
    } catch (_) {
      // Backend might be unreachable — local storage still has the values
    }
  }

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
  Stream<String> sendMessageStream(String content, {String? threadId}) async* {
    final llmApiUrl = await getLlmApiUrl();
    final llmApiKey = await getLlmApiKey();
    final llmModel = await getLlmModel();

    final body = <String, dynamic>{
      'content': content,
    };

    if (llmApiUrl != null && llmApiUrl.isNotEmpty) body['llm_api_url'] = llmApiUrl;
    if (llmApiKey != null && llmApiKey.isNotEmpty) body['llm_api_key'] = llmApiKey;
    if (llmModel != null && llmModel.isNotEmpty) body['llm_model'] = llmModel;
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

  Future<Map<String, dynamic>> getSettings() async {
    final response = await http.get(
      Uri.parse('$baseUrl/api/settings'),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to load settings: ${response.statusCode}');
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
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/api/mcp'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'image': image,
        'env_vars': envVars ?? {},
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

  Future<MCPServer> updateMCPServer(String serverId, String name, String image, Map<String, String> envVars) async {
    final response = await http.patch(
      Uri.parse('$baseUrl/api/mcp/$serverId'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'image': image,
        'env_vars': envVars,
      }),
    );

    if (response.statusCode == 200) {
      return MCPServer.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to update MCP server: ${response.statusCode}');
  }

  Future<void> updateContextSettings({
    required int contextWindow,
    required double compactionThreshold,
    required int preserveRecent,
  }) async {
    await http.patch(
      Uri.parse('$baseUrl/api/settings'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'llm_context_window': contextWindow,
        'llm_compaction_threshold': compactionThreshold,
        'llm_preserve_recent': preserveRecent,
      }),
    );
  }
}
