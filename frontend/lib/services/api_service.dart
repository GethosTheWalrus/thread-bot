import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:threadbot/models/thread.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  final String baseUrl;

  ApiService({this.baseUrl = 'http://localhost:8000'});

  // ── LLM Settings (local storage) ──────────────────────────────────

  Future<String> getLlmApiUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('llm_api_url') ?? 'http://localhost:11434/v1';
  }

  Future<String> getLlmApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('llm_api_key') ?? '';
  }

  Future<String> getLlmModel() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('llm_model') ?? 'llama3.1';
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
  Future<Thread> sendMessage(String content, {String? threadId}) async {
    final llmApiUrl = await getLlmApiUrl();
    final llmApiKey = await getLlmApiKey();
    final llmModel = await getLlmModel();

    final body = <String, dynamic>{
      'content': content,
      'llm_api_url': llmApiUrl,
      'llm_api_key': llmApiKey,
      'llm_model': llmModel,
    };

    if (threadId != null) {
      body['thread_id'] = threadId;
    }

    final response = await http.post(
      Uri.parse('$baseUrl/api/chat'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );

    if (response.statusCode == 200) {
      return Thread.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to send message: ${response.body}');
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
}
