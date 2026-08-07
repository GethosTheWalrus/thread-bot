import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:threadbot/models/message.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/widgets/chat_input.dart';
import 'package:threadbot/widgets/chat_message_list.dart';
import 'package:threadbot/widgets/thread_participant_manager.dart';
import 'package:threadbot/widgets/agent_workspace_ui.dart';
import 'package:threadbot/screens/autonomy_screens.dart';
import 'package:threadbot/services/autonomy_api.dart';

void main() {
  testWidgets('agent workspace identity exposes clear navigation hierarchy', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              AgentBreadcrumb(current: 'Researcher'),
              AgentIdentity(name: 'Researcher', handle: 'research'),
              AgentStatusPill('active'),
            ],
          ),
        ),
      ),
    );
    expect(find.text('Agents'), findsOneWidget);
    expect(find.text('Researcher'), findsWidgets);
    expect(find.text('@research'), findsOneWidget);
    expect(find.text('active'), findsOneWidget);
  });

  testWidgets('agent workspace header stacks actions on narrow screens', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AgentPageHeader(
            eyebrow: 'Workspace',
            title: 'Agents',
            description: 'Manage the agents attached to your Threads.',
            action: FilledButton(onPressed: null, child: Text('New agent')),
          ),
        ),
      ),
    );

    expect(find.text('Agents'), findsOneWidget);
    expect(find.text('New agent'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('agent editor exposes only actionable configuration sections', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: AgentEditorScreen(id: 'agent-1', api: _EditorApi()),
      ),
    );
    await tester.pumpAndSettle();
    final pageScroll = find.byType(Scrollable).first;

    expect(find.text('Status and actions'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Instructions'),
      260,
      scrollable: pageScroll,
    );
    expect(find.text('Instructions'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Capabilities'),
      260,
      scrollable: pageScroll,
    );
    expect(find.text('Capabilities'), findsOneWidget);
    expect(find.text('Manage MCP tools'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Automation'),
      260,
      scrollable: pageScroll,
    );
    expect(find.text('Automation'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Recent runs'),
      260,
      scrollable: pageScroll,
    );
    expect(find.text('Recent runs'), findsOneWidget);

    expect(find.text('Forecast'), findsNothing);
    expect(find.textContaining('canary', findRichText: true), findsNothing);
    expect(find.textContaining('shadow', findRichText: true), findsNothing);
    expect(find.text('Run limits'), findsNothing);
    expect(find.text('Versions'), findsNothing);
    expect(tester.takeException(), isNull);
  });

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
    expect(find.text('@mod'), findsOneWidget);
    expect(find.text('active'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

class _EditorApi extends AutonomyApiService {
  @override
  Future<Agent> agent(String id) async => const Agent(
    id: 'agent-1',
    name: 'Researcher',
    status: 'active',
    executionMode: 'act',
    threadId: 'thread-1',
    threadTitle: 'Research Thread',
    handle: 'researcher',
    isModerator: true,
    activeVersionId: 'version-1',
  );

  @override
  Future<Draft> draft(String id) async => const Draft(
    id: 'draft-1',
    agentId: 'agent-1',
    promptTemplate: 'Research the requested topic.',
    toolSelection: ['mcp:DuckDuckGo:search', 'builtin:calculator'],
    skillSelection: ['source-analysis'],
  );

  @override
  Future<List<Version>> versions(String id) async => const [
    Version(id: 'version-1', agentId: 'agent-1', version: 1),
  ];

  @override
  Future<List<Trigger>> triggers(String id) async => const [];

  @override
  Future<CursorPage<Run>> runs(String id, {String? cursor}) async =>
      const CursorPage([], null);
}
