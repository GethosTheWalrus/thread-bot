import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/models/mcp_server.dart';
import 'package:flutter/foundation.dart'; // For kIsWeb
import 'package:web_socket_channel/web_socket_channel.dart';

class ApiService {
  final String baseUrl;

  ApiService({String? baseUrl})
      : baseUrl = baseUrl ?? (kIsWeb ? Uri.base.origin : 'http://localhost:8000');

  String get _wsBaseUrl {
    final uri = Uri.parse(baseUrl);
    final scheme = uri.scheme == 'https' ? 'wss' : 'ws';
    return uri.replace(scheme: scheme).toString();
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
  /// LLM config is managed server-side — no need to send it per request.
  Stream<String> sendMessageStream(String content, {String? threadId, List<Map<String, dynamic>>? overrides, List<String>? imageUrls}) async* {
    final body = <String, dynamic>{
      'content': content,
    };

    if (threadId != null) body['thread_id'] = threadId;
    if (overrides != null) body['tool_overrides'] = overrides;
    if (imageUrls != null && imageUrls.isNotEmpty) body['image_urls'] = imageUrls;

    final channel = WebSocketChannel.connect(Uri.parse('$_wsBaseUrl/api/chat/ws'));
    try {
      channel.sink.add(jsonEncode(body));
      await for (final message in channel.stream) {
        final text = message is String ? message : utf8.decode(message as List<int>);
        final event = jsonDecode(text) as Map<String, dynamic>;
        final type = event['type'] as String?;
        if (type == 'thread') {
          yield 'THREAD_ID:${event['thread_id']}\n\n';
        } else if (type == 'done') {
          yield '[DONE]';
          break;
        } else if (type == 'error') {
          yield '[ERROR] ${event['content'] ?? 'Unknown error'}';
          break;
        } else {
          yield text;
        }
      }
    } finally {
      await channel.sink.close();
    }
  }

  /// Reconnect to an in-progress generation stream after page refresh.
  /// The backend replays all buffered events from the beginning.
  /// If the thread is not generating (204), the stream completes immediately.
  Stream<String> reconnectStream(String threadId) {
    return _reconnectStreamImpl(threadId);
  }

  Stream<String> _reconnectStreamImpl(String threadId) async* {
    final channel = WebSocketChannel.connect(Uri.parse('$_wsBaseUrl/api/threads/$threadId/ws'));
    try {
      await for (final message in channel.stream) {
        final text = message is String ? message : utf8.decode(message as List<int>);
        final event = jsonDecode(text) as Map<String, dynamic>;
        final type = event['type'] as String?;
        if (type == 'thread') {
          continue;
        } else if (type == 'done') {
          yield '[DONE]';
          break;
        } else if (type == 'error') {
          yield '[ERROR] ${event['content'] ?? 'Unknown error'}';
          break;
        } else {
          yield text;
        }
      }
    } finally {
      await channel.sink.close();
    }
  }

  Future<Thread> createThread({String title = 'New Thread', List<Map<String, dynamic>>? overrides}) async {
    final body = <String, dynamic>{'title': title};
    if (overrides != null) body['tool_overrides'] = overrides;

    final response = await http.post(
      Uri.parse('$baseUrl/api/threads'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
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
    Map<String, dynamic>? registryCredentials,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/api/mcp'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'image': image,
        'env_vars': envVars ?? {},
        'args': args ?? {},
        'registry_credentials': registryCredentials ?? {},
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

  Future<MCPServer> updateMCPServer(
    String serverId,
    String name,
    String image,
    Map<String, String> envVars,
    {Map<String, String>? args, Map<String, String>? registryCredentials}
  ) async {
    final response = await http.patch(
      Uri.parse('$baseUrl/api/mcp/$serverId'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'name': name,
        'image': image,
        'env_vars': envVars,
        'args': args ?? {},
        'registry_credentials': registryCredentials ?? {},
      }),
    );

    if (response.statusCode == 200) {
      return MCPServer.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to update MCP server: ${response.statusCode}');
  }

  // ── Thread Tool Overrides ────────────────────────────────────────

  Future<Map<String, dynamic>> getGlobalToolOverrides() async {
    final response = await http.get(
      Uri.parse('$baseUrl/api/mcp/tool-overrides'),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to load global tool overrides: ${response.statusCode}');
  }

  Future<Map<String, dynamic>> getThreadToolOverrides(String threadId) async {
    final response = await http.get(
      Uri.parse('$baseUrl/api/threads/$threadId/tool-overrides'),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to load tool overrides: ${response.statusCode}');
  }

  Future<void> setThreadToolOverrides(String threadId, List<Map<String, dynamic>> overrides) async {
    final response = await http.put(
      Uri.parse('$baseUrl/api/threads/$threadId/tool-overrides'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'overrides': overrides}),
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to save tool overrides: ${response.statusCode}');
    }
  }

  // ── Discord Integration ───────────────────────────────────────────

  Future<Map<String, dynamic>> getDiscordSettings() async {
    final response = await http.get(Uri.parse('$baseUrl/api/discord/settings'));
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to load Discord settings: ${response.statusCode}');
  }

  Future<Map<String, dynamic>> saveDiscordSettings(Map<String, dynamic> settings) async {
    final response = await http.patch(
      Uri.parse('$baseUrl/api/discord/settings'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(settings),
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to save Discord settings: ${response.statusCode}');
  }

  Future<List<Map<String, dynamic>>> getDiscordServers() async {
    final response = await http.get(Uri.parse('$baseUrl/api/discord/servers'));
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return (data['servers'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
    }
    throw Exception('Failed to load Discord servers: ${response.statusCode}');
  }

  Future<Map<String, dynamic>> getDiscordServerMcpOverrides(String guildId) async {
    final response = await http.get(Uri.parse('$baseUrl/api/discord/servers/$guildId/mcp-overrides'));
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to load Discord server overrides: ${response.statusCode}');
  }

  Future<Map<String, dynamic>> saveDiscordServerMcpOverrides(
    String guildId,
    List<Map<String, dynamic>> overrides,
  ) async {
    final response = await http.put(
      Uri.parse('$baseUrl/api/discord/servers/$guildId/mcp-overrides'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'overrides': overrides}),
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('Failed to save Discord server overrides: ${response.statusCode}');
  }

  Future<DiscordThreadLink> shareThreadToDiscord(
    String threadId, {
    String? guildId,
    String? channelId,
    String? name,
  }) async {
    final body = <String, dynamic>{};
    if (guildId != null && guildId.isNotEmpty) body['guild_id'] = guildId;
    if (channelId != null && channelId.isNotEmpty) body['channel_id'] = channelId;
    if (name != null && name.isNotEmpty) body['name'] = name;

    final response = await http.post(
      Uri.parse('$baseUrl/api/threads/$threadId/discord'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    if (response.statusCode == 200) {
      return DiscordThreadLink.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    throw Exception('Failed to share to Discord: ${response.statusCode} ${response.body}');
  }

 Future<void> unshareThreadFromDiscord(String threadId) async {
    final response = await http.delete(Uri.parse('$baseUrl/api/threads/$threadId/discord'));
    if (response.statusCode != 200) {
      throw Exception('Failed to disable Discord sync: ${response.statusCode}');
    }
  }

  // ── Broadcast WebSocket (push thread-list updates) ──────────────────

  WebSocketChannel subscribeBroadcast() {
    final wsUrl = _wsBaseUrl
        .replaceFirst(RegExp(r'^https?'), r'ws')
        .replaceFirst(RegExp(r'/$'), '');
    return WebSocketChannel.connect(Uri.parse('$wsUrl/api/broadcast/ws'));
  }
}
