import 'package:threadbot/models/message.dart';

Set<String> newlyPersistedMessageIds(
  List<Message> current,
  List<Message> incoming,
) {
  final currentIds = current
      .map((message) => message.id)
      .where((id) => !id.startsWith('temp-'))
      .toSet();
  return incoming
      .map((message) => message.id)
      .where((id) => !id.startsWith('temp-') && !currentIds.contains(id))
      .toSet();
}

bool shouldFollowIncomingMessages({
  required bool wasAtBottomBeforeFetch,
  required bool isAtBottomWhenApplying,
}) => wasAtBottomBeforeFetch && isAtBottomWhenApplying;

bool shouldDispatchQueuedReconciliation({
  required bool forceQueued,
  required bool hasAssistantPlaceholder,
}) => forceQueued || !hasAssistantPlaceholder;
