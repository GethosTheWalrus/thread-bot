import 'package:intl/intl.dart';

class MCPTool {
  final String name;
  final String description;

  const MCPTool({required this.name, required this.description});

  factory MCPTool.fromJson(dynamic value) {
    final json = value is Map
        ? Map<String, dynamic>.fromEntries(
            value.entries
                .where((entry) => entry.key is String)
                .map((entry) => MapEntry(entry.key as String, entry.value)),
          )
        : const <String, dynamic>{};
    return MCPTool(
      name: json['name']?.toString() ?? '',
      description: json['description']?.toString() ?? '',
    );
  }

  Map<String, dynamic> toJson() => {'name': name, 'description': description};
}

class MCPServer {
  final String id;
  final String name;
  final String image;
  final Map<String, dynamic> envVars;
  final Map<String, dynamic> args;
  final Map<String, dynamic> registryCredentials;
  final bool isActive;
  final DateTime createdAt;
  final List<MCPTool> tools;
  final Map<String, String> toolSafetyOverrides;

  MCPServer({
    required this.id,
    required this.name,
    required this.image,
    required this.envVars,
    required this.args,
    required this.registryCredentials,
    required this.isActive,
    required this.createdAt,
    this.tools = const [],
    this.toolSafetyOverrides = const {},
  });

  static Map<String, dynamic> _mapValue(dynamic value) {
    return value is Map
        ? Map<String, dynamic>.fromEntries(
            value.entries
                .where((entry) => entry.key is String)
                .map((entry) => MapEntry(entry.key as String, entry.value)),
          )
        : <String, dynamic>{};
  }

  factory MCPServer.fromJson(Map<String, dynamic> json) {
    final rawTools = json['tools'] is List ? json['tools'] as List : const [];
    final rawOverrides = json['tool_safety_overrides'] is Map
        ? json['tool_safety_overrides'] as Map
        : const {};
    return MCPServer(
      id: json['id']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      image: json['image']?.toString() ?? '',
      envVars: _mapValue(json['env_vars']),
      args: _mapValue(json['args']),
      registryCredentials: _mapValue(json['registry_credentials']),
      isActive: json['is_active'] is bool ? json['is_active'] as bool : true,
      createdAt:
          DateTime.tryParse(json['created_at']?.toString() ?? '') ??
          DateTime.fromMillisecondsSinceEpoch(0),
      tools: rawTools
          .map(MCPTool.fromJson)
          .where((tool) => tool.name.isNotEmpty)
          .toList(),
      toolSafetyOverrides: Map.fromEntries(
        rawOverrides.entries
            .where(
              (entry) =>
                  entry.key is String &&
                  (entry.value == 'read_only' || entry.value == 'effectful'),
            )
            .map(
              (entry) => MapEntry(entry.key as String, entry.value as String),
            ),
      ),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'image': image,
      'env_vars': envVars,
      'args': args,
      'registry_credentials': registryCredentials,
      'is_active': isActive,
      'created_at': createdAt.toIso8601String(),
      'tools': tools.map((tool) => tool.toJson()).toList(),
      'tool_safety_overrides': toolSafetyOverrides,
    };
  }

  String get formattedDate => DateFormat('MMM d, yyyy').format(createdAt);
}
