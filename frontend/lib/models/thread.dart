import 'package:threadbot/models/message.dart';

class Thread {
  final String id;
  final String title;
  final String? parentId;
  final DateTime createdAt;
  final DateTime updatedAt;
  final List<Message> messages;
  final bool isGenerating;
  final DiscordThreadLink? discordLink;
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
    this.discordLink,
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
      discordLink: json['discord_link'] != null
          ? DiscordThreadLink.fromJson(json['discord_link'] as Map<String, dynamic>)
          : null,
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
  final bool isDiscordThread;

  ThreadListItem({
    required this.id,
    required this.title,
    this.parentId,
    required this.createdAt,
    required this.updatedAt,
    required this.messageCount,
    this.isDiscordThread = false,
  });

  factory ThreadListItem.fromJson(Map<String, dynamic> json) {
    return ThreadListItem(
      id: json['id'] as String,
      title: json['title'] as String,
      parentId: json['parent_id'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      messageCount: json['message_count'] as int? ?? 0,
      isDiscordThread: json['is_discord_thread'] as bool? ?? false,
    );
  }
}

class DiscordThreadLink {
  final String threadId;
  final String guildId;
  final String channelId;
  final String discordThreadId;
  final String discordThreadName;
  final bool isActive;

  DiscordThreadLink({
    required this.threadId,
    required this.guildId,
    required this.channelId,
    required this.discordThreadId,
    required this.discordThreadName,
    required this.isActive,
  });

  factory DiscordThreadLink.fromJson(Map<String, dynamic> json) {
    return DiscordThreadLink(
      threadId: json['thread_id'] as String,
      guildId: json['guild_id'] as String,
      channelId: json['channel_id'] as String,
      discordThreadId: json['discord_thread_id'] as String,
      discordThreadName: json['discord_thread_name'] as String,
      isActive: json['is_active'] as bool? ?? true,
    );
  }
}
