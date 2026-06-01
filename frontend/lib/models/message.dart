class Message {
  final String id;
  final String threadId;
  final String role;
  String content;  // mutable so streaming can append tokens
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
  bool get isToolCall => role == 'tool_call';
  bool get isToolResult => role == 'tool_result';
  bool get isSystem => role == 'system';
  bool get isThinking => role == 'thinking';
  bool get isFromDiscord => metadata?['source'] == 'discord';

  String get senderLabel {
    if (isUser) {
      final senderName = metadata?['sender_name'] as String?;
      if (senderName != null && senderName.isNotEmpty) return senderName;
      final legacyDiscordSeparator = content.indexOf(' (Discord): ');
      if (legacyDiscordSeparator > 0) return content.substring(0, legacyDiscordSeparator);
      return 'User';
    }
    if (isAssistant) return 'ThreadBot';
    return role;
  }

  String get displayContent {
    final legacyDiscordSeparator = content.indexOf(' (Discord): ');
    if (!isFromDiscord && legacyDiscordSeparator <= 0) return content;
    final senderName = metadata?['sender_name'] as String?;
    if (senderName != null && senderName.isNotEmpty) {
      final prefix = '$senderName (Discord): ';
      if (content.startsWith(prefix)) return content.substring(prefix.length);
    }
    if (legacyDiscordSeparator > 0) {
      return content.substring(legacyDiscordSeparator + ' (Discord): '.length);
    }
    return content;
  }

  bool get isCompactionSummary =>
      role == 'system' &&
      (metadata?['type'] == 'compaction_summary' ||
       metadata?['type'] == 'compaction_event');
}
