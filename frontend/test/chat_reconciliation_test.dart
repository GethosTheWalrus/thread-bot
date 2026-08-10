import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:threadbot/models/message.dart';
import 'package:threadbot/utils/chat_reconciliation.dart';
import 'package:threadbot/widgets/chat_message_list.dart';

Message _message(String id, String content) => Message(
  id: id,
  threadId: 'thread',
  role: 'user',
  content: content,
  createdAt: DateTime(2026),
);

void main() {
  test('new persisted IDs exclude temporary messages', () {
    final current = [_message('server-1', 'old'), _message('temp-ast-1', '')];
    final incoming = [
      _message('server-1', 'old'),
      _message('temp-ast-1', ''),
      _message('server-2', 'new'),
      _message('temp-2', 'optimistic'),
    ];

    expect(newlyPersistedMessageIds(current, incoming), {'server-2'});
  });

  test('following the bottom requires both bottom snapshots', () {
    expect(
      shouldFollowIncomingMessages(
        wasAtBottomBeforeFetch: true,
        isAtBottomWhenApplying: true,
      ),
      isTrue,
    );
    expect(
      shouldFollowIncomingMessages(
        wasAtBottomBeforeFetch: true,
        isAtBottomWhenApplying: false,
      ),
      isFalse,
    );
    expect(
      shouldFollowIncomingMessages(
        wasAtBottomBeforeFetch: false,
        isAtBottomWhenApplying: true,
      ),
      isFalse,
    );
  });

  test('forced queued reconciliation dispatches through a placeholder', () {
    expect(
      shouldDispatchQueuedReconciliation(
        forceQueued: true,
        hasAssistantPlaceholder: true,
      ),
      isTrue,
    );
    expect(
      shouldDispatchQueuedReconciliation(
        forceQueued: false,
        hasAssistantPlaceholder: true,
      ),
      isFalse,
    );
  });

  testWidgets('only requested newly mounted message gets entrance animation', (
    tester,
  ) async {
    final messages = [_message('old', 'old'), _message('new', 'new')];
    await tester.pumpWidget(
      MaterialApp(
        home: SizedBox(
          height: 500,
          child: ChatMessageList(
            messages: messages,
            scrollController: ScrollController(),
            animatedMessageIds: const {'new'},
          ),
        ),
      ),
    );

    expect(find.byKey(const ValueKey('message-old')), findsOneWidget);
    expect(find.byKey(const ValueKey('message-new')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('message-new')),
        matching: find.byType(FadeTransition),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('message-old')),
        matching: find.byType(FadeTransition),
      ),
      findsNothing,
    );
  });
}
