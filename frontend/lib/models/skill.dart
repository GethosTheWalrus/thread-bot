class Skill {
  final String id;
  final String name;
  final String description;
  final String content;
  final bool isActive;
  final DateTime createdAt;

  Skill({
    required this.id,
    required this.name,
    required this.description,
    required this.content,
    required this.isActive,
    required this.createdAt,
  });

  factory Skill.fromJson(Map<String, dynamic> json) {
    return Skill(
      id: json['id'] as String,
      name: json['name'] as String? ?? '',
      description: json['description'] as String? ?? '',
      content: json['content'] as String? ?? '',
      isActive: json['is_active'] as bool? ?? true,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}
