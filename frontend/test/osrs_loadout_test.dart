import 'package:flutter_test/flutter_test.dart';
import 'package:threadbot/models/osrs_loadout.dart';

void main() {
  test('accepts camelCase equipment variables', () {
    final item = OsrsEquipmentItem.fromJson({
      'id': 12926,
      'itemVars': {'charges': 3},
    });

    expect(item.itemVars['charges'], 3);
    expect(item.toJson()['item_vars'], {'charges': 3});
  });

  test('normalizes Wiki top-level combat and potion fields', () {
    final payload = OsrsLoadoutPayload.fromJson({
      'equipment': {
        'weapon': {'id': 1, 'item_vars': {}},
      },
      'skills': {'atk': 99},
      'boosts': {},
      'buffs': {
        'potions': [4, 7],
        'in_wilderness': true,
      },
      'stance': 'Aggressive',
      'attackType': 'slash',
      'spell': 'Ice Barrage',
    });

    expect(payload.potions, [4, 7]);
    expect(payload.combat['stance'], 'Aggressive');
    expect(payload.combat['attack_type'], 'slash');
    expect(payload.combat['spell'], 'Ice Barrage');
    expect(payload.equipment['weapon']!.itemVars, isEmpty);
  });
}
