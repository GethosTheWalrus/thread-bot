class Message {
  final String id;
  final String threadId;
  final String role;
  String content; // mutable so streaming can append tokens
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
      if (legacyDiscordSeparator > 0)
        return content.substring(0, legacyDiscordSeparator);
      return 'User';
    }
    if (isAssistant) return 'ThreadBot';
    return role;
  }

  String get displayContent {
    final legacyDiscordSeparator = content.indexOf(' (Discord): ');
    var text = content;
    final senderName = metadata?['sender_name'] as String?;
    if (senderName != null && senderName.isNotEmpty) {
      final prefix = '$senderName (Discord): ';
      if (text.startsWith(prefix)) text = text.substring(prefix.length);
    }
    if (legacyDiscordSeparator > 0) {
      text = text.substring(legacyDiscordSeparator + ' (Discord): '.length);
    }
    text = text
        .split('\n')
        .where((line) {
          if (line.startsWith('Image attachment: ')) return false;
          // Hide standalone generated media links; those render inline below the text.
          final trimmed = line.trim();
          if (_isStandaloneGeneratedMediaLine(trimmed)) return false;
          if ((content.contains('/api/generated-media/') ||
                  content.contains('/api/generated-images/')) &&
              (trimmed.startsWith('<video') ||
                  trimmed.startsWith('</video') ||
                  trimmed == 'Your browser does not support the video tag.')) {
            return false;
          }
          if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
            final lower = trimmed.toLowerCase();
            if (lower.contains('cdn.discordapp.com') ||
                lower.contains('/api/generated-images/') ||
                lower.contains('/api/generated-media/')) {
              return false;
            }
          }
          return true;
        })
        .join('\n')
        .trim();
    return text;
  }

  bool get isCompactionSummary =>
      role == 'system' && metadata?['type'] == 'compaction_event';

  List<Map<String, dynamic>> get imageAttachments {
    final attachments = metadata?['image_attachments'];
    if (attachments is List && attachments.isNotEmpty) {
      return attachments
          .whereType<Map>()
          .map(
            (item) => item.map((key, value) => MapEntry(key.toString(), value)),
          )
          .toList();
    }
    // Fallback: parse URLs from legacy "Image attachment: <name> <url>" lines
    // and from bare Discord/generated-image URLs that appear on their own line.
    final urls = <Map<String, dynamic>>[];
    final seen = <String>{};
    for (final line in content.split('\n')) {
      final match = RegExp(
        r'Image attachment: \S+\s+(https?://\S+)',
      ).firstMatch(line);
      if (match != null) {
        final url = match.group(1) ?? '';
        if (url.isNotEmpty && seen.add(url)) {
          urls.add({'url': url, 'filename': url.split('/').last});
        }
        continue;
      }
      final trimmed = line.trim();
      if ((trimmed.startsWith('http://') || trimmed.startsWith('https://')) &&
          (trimmed.toLowerCase().contains('cdn.discordapp.com') ||
              trimmed.contains('/api/generated-images/')) &&
          seen.add(trimmed)) {
        urls.add({'url': trimmed, 'filename': trimmed.split('/').last});
      }
    }
    return urls;
  }

  List<Map<String, dynamic>> get generatedMediaAttachments {
    final media = <Map<String, dynamic>>[];
    final seen = <String>{};

    void addUrl(String url) {
      final clean = url.trim();
      if (clean.isEmpty || !seen.add(clean)) return;
      final lower = clean.toLowerCase();
      final isImage =
          lower.contains('/api/generated-images/') ||
          lower.endsWith('.png') ||
          lower.endsWith('.jpg') ||
          lower.endsWith('.jpeg') ||
          lower.endsWith('.webp') ||
          lower.endsWith('.gif');
      final isVideo =
          lower.contains('/api/generated-media/') ||
          lower.endsWith('.mp4') ||
          lower.endsWith('.webm') ||
          lower.endsWith('.mov');
      if (!isImage && !isVideo) return;
      media.add({
        'url': clean,
        'filename': clean.split('/').last.split('?').first,
        'type': isVideo ? 'video' : 'image',
      });
    }

    final markdownLinks = RegExp(r'!?\[[^\]]*\]\(([^)]+)\)');
    for (final match in markdownLinks.allMatches(content)) {
      final url = match.group(1) ?? '';
      if (url.contains('/api/generated-images/') ||
          url.contains('/api/generated-media/')) {
        addUrl(url);
      }
    }

    final srcLinks = RegExp(r'''src=["']([^"']+)["']''', caseSensitive: false);
    for (final match in srcLinks.allMatches(content)) {
      final url = match.group(1) ?? '';
      if (url.contains('/api/generated-images/') ||
          url.contains('/api/generated-media/')) {
        addUrl(url);
      }
    }

    final bareLinks = RegExp(
      r'(?:https?://\S+|/api/generated-(?:images|media)/\S+)',
    );
    for (final match in bareLinks.allMatches(content)) {
      addUrl((match.group(0) ?? '').replaceAll(RegExp(r'[)>.,]+$'), ''));
    }

    return media;
  }

  static bool _isStandaloneGeneratedMediaLine(String line) {
    if (!line.contains('/api/generated-images/') &&
        !line.contains('/api/generated-media/')) {
      return false;
    }
    if (RegExp(r'^!?\[[^\]]*\]\([^)]+\)$').hasMatch(line)) return true;
    if (RegExp(
      r'^(?:https?://\S+|/api/generated-(?:images|media)/\S+)$',
    ).hasMatch(line))
      return true;
    if (RegExp(r'^<source\s+[^>]*>$', caseSensitive: false).hasMatch(line))
      return true;
    return false;
  }
}
