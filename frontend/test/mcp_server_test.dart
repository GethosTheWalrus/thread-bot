import 'package:flutter_test/flutter_test.dart';
import 'package:threadbot/models/mcp_server.dart';

void main() {
  test('MCP server safely parses tools and safety overrides', () {
    final server = MCPServer.fromJson({
      'id': 'server-1',
      'name': 'Files',
      'image': 'mcp/files:latest',
      'env_vars': null,
      'args': 'invalid',
      'registry_credentials': {},
      'created_at': '2026-01-01T00:00:00Z',
      'tools': [
        {'name': 'read_file', 'description': 'Read a file'},
        {'name': 'write_file'},
        'invalid',
      ],
      'tool_safety_overrides': {
        'read_file': 'read_only',
        'stale_tool': 'effectful',
        'invalid': 'unknown',
      },
    });

    expect(server.tools.map((tool) => tool.name), ['read_file', 'write_file']);
    expect(server.tools[1].description, isEmpty);
    expect(server.toolSafetyOverrides, {
      'read_file': 'read_only',
      'stale_tool': 'effectful',
    });
    expect(
      server.toJson()['tool_safety_overrides'],
      server.toolSafetyOverrides,
    );
    expect((server.toJson()['tools'] as List).length, 2);
  });
}
