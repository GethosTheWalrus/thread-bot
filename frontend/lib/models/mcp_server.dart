import 'package:intl/intl.dart';

class MCPServer {
  final String id;
  final String name;
  final String image;
  final Map<String, dynamic> envVars;
  final Map<String, dynamic> args;
  final bool isActive;
  final DateTime createdAt;

  MCPServer({
    required this.id,
    required this.name,
    required this.image,
    required this.envVars,
    required this.args,
    required this.isActive,
    required this.createdAt,
  });

  factory MCPServer.fromJson(Map<String, dynamic> json) {
    return MCPServer(
      id: json['id'],
      name: json['name'],
      image: json['image'],
      envVars: Map<String, dynamic>.from(json['env_vars'] ?? {}),
      args: Map<String, dynamic>.from(json['args'] ?? {}),
      isActive: json['is_active'] ?? true,
      createdAt: DateTime.parse(json['created_at']),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'image': image,
      'env_vars': envVars,
      'args': args,
      'is_active': isActive,
      'created_at': createdAt.toIso8601String(),
    };
  }

  String get formattedDate => DateFormat('MMM d, yyyy').format(createdAt);
}
