import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:threadbot/models/message.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/widgets/chat_input.dart';
import 'package:threadbot/widgets/chat_message_list.dart';
import 'package:threadbot/widgets/thread_participant_manager.dart';

void main() {
  test('thread plural contracts fall back to legacy scalar fields', () {
    final thread = Thread.fromJson({
      'id': 't',
      'title': 'T',
      'created_at': '2026-01-01T00:00:00Z',
      'updated_at': '2026-01-01T00:00:00Z',
      'agent': {
        'id': 'a',
        'name': 'Alpha',
        'mention_name': 'alpha',
        'is_moderator': true,
      },
      'latest_active_run': {'id': 'r', 'status': 'queued', 'mode': 'live'},
    });
    expect(thread.agents.single.mentionName, 'alpha');
    expect(thread.agents.single.isModerator, isTrue);
    expect(thread.activeRuns.single.id, 'r');
  });

  test('thread preserves independent active run identities', () {
    final thread = Thread.fromJson({
      'id': 't',
      'title': 'T',
      'created_at': '2026-01-01T00:00:00Z',
      'updated_at': '2026-01-01T00:00:00Z',
      'active_runs': [
        {
          'id': 'run-a',
          'status': 'running',
          'mode': 'live',
          'agent_name': 'Researcher',
          'agent_handle': 'research',
          'output_summary': 'Reading sources',
        },
        {
          'id': 'run-b',
          'status': 'waiting_approval',
          'mode': 'live',
          'agent_name': 'Reviewer',
          'agent_handle': 'review',
        },
      ],
    });

    expect(thread.activeRuns, hasLength(2));
    expect(thread.activeRuns[0].agentName, 'Researcher');
    expect(thread.activeRuns[0].agentHandle, 'research');
    expect(thread.activeRuns[1].status, 'waiting_approval');
  });

  test('mention parser respects boundaries and escaping', () {
    expect(mentionQueryAtCaret('@Al', 3), 'Al');
    expect(mentionQueryAtCaret('hello @Al', 9), 'Al');
    expect(mentionQueryAtCaret('hello x@Al', 9), isNull);
    expect(mentionQueryAtCaret(r'hello \@Al', 10), isNull);
  });

  test('attributed assistant labels preserve ThreadBot fallback', () {
    final base = {
      'id': 'm',
      'thread_id': 't',
      'role': 'assistant',
      'content': 'hi',
      'created_at': '2026-01-01T00:00:00Z',
    };
    expect(Message.fromJson(base).senderLabel, 'ThreadBot');
    expect(
      Message.fromJson({
        ...base,
        'agent_id': 'a',
        'agent_name': 'Alpha',
        'agent_mention_name': 'alpha',
      }).senderLabel,
      'Alpha @alpha',
    );
  });

  test('agent parses its owning thread title', () {
    final agent = Agent.fromJson({
      'id': 'a',
      'thread_id': 't',
      'thread_title': 'Temporal Operations',
      'name': 'Operator',
      'status': 'active',
      'execution_mode': 'act',
      'created_at': '2026-01-01T00:00:00Z',
      'updated_at': '2026-01-01T00:00:00Z',
    });
    expect(agent.threadTitle, 'Temporal Operations');
  });

  test('active run presentations keep events scoped to their run', () {
    final first = ActiveRunPresentation(
      run: Run(
        id: 'run-a',
        status: 'running',
        agentName: 'Researcher',
        inputMessageId: 'm-a',
      ),
      events: const [RunEvent(type: 'planning')],
    );
    final second = ActiveRunPresentation(
      run: Run(
        id: 'run-b',
        status: 'waiting_approval',
        agentName: 'Reviewer',
        inputMessageId: 'm-b',
      ),
      events: const [RunEvent(type: 'action_started')],
    );

    expect(first.id, isNot(second.id));
    expect(first.events.single.type, 'planning');
    expect(second.events.single.type, 'action_started');
    expect(first.inputMessageId, 'm-a');
    expect(second.inputMessageId, 'm-b');
  });

  testWidgets(
    'concurrent agent bubbles have independent skeletons and anchors',
    (tester) async {
      final messages = [
        Message(
          id: 'm-a',
          threadId: 't',
          role: 'user',
          content: 'research',
          createdAt: DateTime(2026),
        ),
        Message(
          id: 'm-b',
          threadId: 't',
          role: 'user',
          content: 'review',
          createdAt: DateTime(2026),
        ),
      ];
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ChatMessageList(
              messages: messages,
              scrollController: ScrollController(),
              activeRuns: [
                ActiveRunPresentation(
                  run: Run(
                    id: 'run-a',
                    status: 'running',
                    agentName: 'Researcher',
                    agentHandle: 'research',
                    inputMessageId: 'm-a',
                  ),
                  events: const [
                    RunEvent(
                      type: 'action_planned',
                      payload: {'tool_identity': 'mcp:DuckDuckGo:search'},
                    ),
                  ],
                ),
                ActiveRunPresentation(
                  run: Run(
                    id: 'run-b',
                    status: 'waiting_approval',
                    agentName: 'Reviewer',
                    agentHandle: 'review',
                    inputMessageId: 'm-b',
                  ),
                  events: const [RunEvent(type: 'approval_requested')],
                ),
              ],
            ),
          ),
        ),
      );
      await tester.pump();

      expect(find.text('RESEARCHER @RESEARCH'), findsOneWidget);
      expect(find.text('REVIEWER @REVIEW'), findsOneWidget);
      expect(find.text('running'), findsOneWidget);
      expect(find.text('waiting approval'), findsOneWidget);
      expect(
        find.byWidgetPredicate(
          (widget) =>
              widget is Tooltip &&
              widget.message == 'Using mcp:DuckDuckGo:search',
        ),
        findsOneWidget,
      );
      expect(find.byType(FractionallySizedBox), findsAtLeastNWidgets(10));
    },
  );

  testWidgets('embedded participant manager presents unified agent controls', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SizedBox(
            height: 700,
            child: ThreadParticipantManager(
              threadId: 'thread-1',
              embedded: true,
              participants: [
                ThreadAgentSummary(
                  id: 'agent-1',
                  name: 'Moderator',
                  status: 'active',
                  executionMode: 'act',
                  mentionName: 'mod',
                  isModerator: true,
                ),
              ],
            ),
          ),
        ),
      ),
    );

    expect(find.text('Agents in this thread'), findsOneWidget);
    expect(find.text('Moderator'), findsWidgets);
    expect(find.text('Details & settings'), findsOneWidget);
    expect(find.text('Heartbeat'), findsOneWidget);
    expect(find.text('Agent tools'), findsOneWidget);
    expect(find.text('@mod · active'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
