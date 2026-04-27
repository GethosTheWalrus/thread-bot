class Message {
  final String id;
  final String threadId;
  final String role;
  final String content;
  final DateTime createdAt;
  final Map<String, dynamic>? metadata;

  Message({
    required this.id,
    required this.threadId,
    required this.role,
    required this.content,
    required this.createdAt,
    this.metadata,
  });

  factory Message.fromJson(Map<String, dynamic> json) {
    return Message(
      id: json['id'] as String,
      threadId: json['thread_id'] as String,
      role: json['role'] as String,
      content: json['content'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
      metadata: json['metadata'] as Map<String, dynamic>?,
    );
  }

  bool get isUser => role == 'user';
  bool get isAssistant => role == 'assistant';
}
