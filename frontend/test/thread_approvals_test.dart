import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:threadbot/models/phase2.dart';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/services/phase2_api.dart';

void main() {
  test('approval parses thread and agent identity fields', () {
    final approval = Approval.fromJson({
      'id': 'a1',
      'run_id': 'r1',
      'action_id': 'act',
      'status': 'pending',
      'risk_level': 'high',
      'request_hash': 'hash',
      'thread_id': 'thread-1',
      'agent_id': 'agent-1',
      'agent_name': 'Researcher',
      'agent_handle': 'research',
      'tool_identity': 'mcp:search',
    });
    expect(approval.threadId, 'thread-1');
    expect(approval.agentName, 'Researcher');
    expect(approval.toolIdentity, 'mcp:search');
  });

  test('approvals uses the scoped thread query', () async {
    Uri? requested;
    final api = Phase2ApiService(
      AutonomyApiService(
        baseUrl: 'http://localhost',
        client: MockClient((request) async {
          requested = request.url;
          return http.Response('[]', 200);
        }),
      ),
    );
    await api.approvals(threadId: 'thread/1');
    expect(requested?.path, '/api/approvals');
    expect(requested?.queryParameters['thread_id'], 'thread/1');
  });

  test(
    'thread approval preset defaults safely and parses supported values',
    () {
      final base = {
        'id': 'thread-1',
        'title': 'Thread',
        'created_at': '2026-01-01T00:00:00Z',
        'updated_at': '2026-01-01T00:00:00Z',
      };
      expect(Thread.fromJson(base).approvalPreset, 'effectful');
      expect(
        ThreadListItem.fromJson({
          ...base,
          'approval_preset': 'never',
        }).approvalPreset,
        'never',
      );
      expect(
        ThreadListItem.fromJson({
          ...base,
          'approval_preset': 'invalid',
        }).approvalPreset,
        'effectful',
      );
    },
  );

  test('setting a thread approval preset uses the dedicated endpoint', () async {
    Uri? requested;
    String? requestBody;
    final api = ApiService(
      baseUrl: 'http://localhost',
      client: MockClient((request) async {
        requested = request.url;
        requestBody = request.body;
        return http.Response(
          '{"id":"thread-1","title":"Thread","created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z","approval_preset":"all"}',
          200,
        );
      }),
    );
    final thread = await api.setThreadApprovalPreset('thread-1', 'all');
    expect(requested?.path, '/api/threads/thread-1/approval-preset');
    expect(requestBody, '{"approval_preset":"all"}');
    expect(thread.approvalPreset, 'all');
  });

  test(
    'thread settings keep the roster in Overview and omit workspace shortcuts',
    () {
      final source = File('lib/screens/chat_screen.dart').readAsStringSync();
      final overview = source.substring(
        source.indexOf("const Tab(text: 'Overview')"),
        source.indexOf('class _ContextTab'),
      );
      expect(overview, contains('ThreadParticipantManager'));
      expect(overview, isNot(contains('All agents')));
      expect(overview, isNot(contains('App settings')));
      expect(overview, isNot(contains('MCP servers')));
      expect(overview, isNot(contains('Skills')));
    },
  );
}
