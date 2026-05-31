import 'package:threadbot/models/message.dart';

class Thread {
  final String id;
  final String title;
  final String? parentId;
  final DateTime createdAt;
  final DateTime updatedAt;
  final List<Message> messages;
  final bool isGenerating;
  final int estimatedTokens;
  final int contextWindow;

  Thread({
    required this.id,
    required this.title,
    this.parentId,
    required this.createdAt,
    required this.updatedAt,
    this.messages = const [],
    this.isGenerating = false,
    this.estimatedTokens = 0,
    this.contextWindow = 8192,
  });

  factory Thread.fromJson(Map<String, dynamic> json) {
    final messagesJson = json['messages'] as List<dynamic>? ?? [];
    final messages = messagesJson
        .map((m) => Message.fromJson(m as Map<String, dynamic>))
        .toList();

    return Thread(
      id: json['id'] as String,
      title: json['title'] as String,
      parentId: json['parent_id'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      messages: messages,
      isGenerating: json['is_generating'] as bool? ?? false,
      estimatedTokens: json['estimated_tokens'] as int? ?? 0,
      contextWindow: json['context_window'] as int? ?? 8192,
    );
  }

  /// Last message content for preview
  String get lastMessagePreview {
    if (messages.isEmpty) return 'No messages yet';
    return messages.last.content;
  }
}

class ThreadListItem {
  final String id;
  String title;
  final String? parentId;
  final DateTime createdAt;
  final DateTime updatedAt;
  final int messageCount;

  ThreadListItem({
    required this.id,
    required this.title,
    this.parentId,
    required this.createdAt,
    required this.updatedAt,
    required this.messageCount,
  });

  factory ThreadListItem.fromJson(Map<String, dynamic> json) {
    return ThreadListItem(
      id: json['id'] as String,
      title: json['title'] as String,
      parentId: json['parent_id'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      messageCount: json['message_count'] as int? ?? 0,
    );
  }
}
