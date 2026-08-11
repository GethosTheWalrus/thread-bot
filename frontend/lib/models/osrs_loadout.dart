class OsrsEquipmentItem {
  final int id;
  final String? version;
  final String? name;
  final Map<String, dynamic> itemVars;

  const OsrsEquipmentItem({
    required this.id,
    this.version,
    this.name,
    this.itemVars = const {},
  });
  factory OsrsEquipmentItem.fromJson(Map<String, dynamic> j) =>
      OsrsEquipmentItem(
        id:
            (j['id'] as num?)?.toInt() ??
            int.tryParse('${j['id'] ?? ''}') ??
            int.tryParse('${j['item_id'] ?? ''}') ??
            0,
        version: j['version']?.toString(),
        name: j['name']?.toString(),
        itemVars: Map<String, dynamic>.from(
          (j['itemVars'] as Map?) ?? (j['item_vars'] as Map?) ?? {},
        ),
      );
  Map<String, dynamic> toJson() => {
    'id': id,
    if (version != null) 'version': version,
    if (name != null) 'name': name,
    'item_vars': itemVars,
  };
}

const osrsSlots = [
  'head',
  'cape',
  'neck',
  'ammo',
  'weapon',
  'body',
  'shield',
  'legs',
  'hands',
  'feet',
  'ring',
];

class OsrsLoadoutPayload {
  final Map<String, OsrsEquipmentItem?> equipment;
  final Map<String, int> skills;
  final Map<String, int> boosts;
  final List<int> prayers;
  final List<int> potions;
  final Map<String, dynamic> buffs;
  final Map<String, dynamic> combat;
  const OsrsLoadoutPayload({
    required this.equipment,
    required this.skills,
    required this.boosts,
    this.prayers = const [],
    this.potions = const [],
    this.buffs = const {},
    this.combat = const {},
  });
  factory OsrsLoadoutPayload.empty() => OsrsLoadoutPayload(
    equipment: {for (final s in osrsSlots) s: null},
    skills: {
      for (final s in [
        'atk',
        'str',
        'def',
        'hp',
        'ranged',
        'magic',
        'prayer',
        'mining',
        'herblore',
      ])
        s: 1,
    },
    boosts: {
      for (final s in [
        'atk',
        'str',
        'def',
        'hp',
        'ranged',
        'magic',
        'prayer',
        'mining',
        'herblore',
      ])
        s: 0,
    },
    buffs: {
      'on_slayer_task': false,
      'in_wilderness': false,
      'forinthry_surge': false,
      'soulreaper_stacks': 0,
      'ba_attacker_level': 0,
      'chinchompa_distance': 4,
      'kandarin_diary': false,
      'charge_spell': false,
      'mark_of_darkness_spell': false,
      'using_sunfire_runes': false,
    },
    combat: {},
  );
  factory OsrsLoadoutPayload.fromJson(Map<String, dynamic> j) {
    final raw = j['loadout'] is Map
        ? Map<String, dynamic>.from(j['loadout'] as Map)
        : j;
    final rawBuffs = Map<String, dynamic>.from(raw['buffs'] as Map? ?? {});
    final rawCombat = Map<String, dynamic>.from(raw['combat'] as Map? ?? {});
    final potions = raw['potions'] is List
        ? raw['potions'] as List
        : rawBuffs['potions'] is List
        ? rawBuffs['potions'] as List
        : const [];
    final equipment = Map<String, OsrsEquipmentItem?>.fromEntries(
      osrsSlots.map((s) {
        final value = (raw['equipment'] as Map?)?[s];
        return MapEntry(
          s,
          value is Map
              ? OsrsEquipmentItem.fromJson(Map<String, dynamic>.from(value))
              : null,
        );
      }),
    );
    Map<String, int> ints(String key, List<String> names) => {
      for (final n in names) n: ((raw[key] as Map?)?[n] as num?)?.toInt() ?? 0,
    };
    return OsrsLoadoutPayload(
      equipment: equipment,
      skills: ints('skills', [
        'atk',
        'str',
        'def',
        'hp',
        'ranged',
        'magic',
        'prayer',
        'mining',
        'herblore',
      ]),
      boosts: ints('boosts', [
        'atk',
        'str',
        'def',
        'hp',
        'ranged',
        'magic',
        'prayer',
        'mining',
        'herblore',
      ]),
      prayers: ((raw['prayers'] as List?) ?? [])
          .whereType<num>()
          .map((x) => x.toInt())
          .toList(),
      potions: potions.whereType<num>().map((x) => x.toInt()).toList(),
      buffs: {...rawBuffs}..remove('potions'),
      combat: {
        ...rawCombat,
        if (raw['stance'] != null) 'stance': raw['stance'],
        if (raw['attackType'] != null) 'attack_type': raw['attackType'],
        if (raw['attack_type'] != null) 'attack_type': raw['attack_type'],
        if (raw['spell'] != null) 'spell': raw['spell'],
      },
    );
  }
  Map<String, dynamic> toJson() => {
    'schema_version': 1,
    'equipment': {for (final e in equipment.entries) e.key: e.value?.toJson()},
    'skills': skills,
    'boosts': boosts,
    'prayers': prayers,
    'potions': potions,
    'buffs': {...buffs}..remove('potions'),
    'combat': combat,
  };
}

class OsrsLoadout {
  final String id, name, sourceType;
  final String? description, sourceRef, engineRevision;
  final OsrsLoadoutPayload loadout;
  final int revision;
  final bool isDefault;
  const OsrsLoadout({
    required this.id,
    required this.name,
    required this.sourceType,
    required this.loadout,
    required this.revision,
    required this.isDefault,
    this.description,
    this.sourceRef,
    this.engineRevision,
  });
  factory OsrsLoadout.fromJson(Map<String, dynamic> j) => OsrsLoadout(
    id: '${j['id']}',
    name: '${j['name']}',
    sourceType: '${j['source_type'] ?? 'manual'}',
    description: j['description']?.toString(),
    sourceRef: j['source_ref']?.toString(),
    engineRevision: j['engine_revision']?.toString(),
    loadout: OsrsLoadoutPayload.fromJson(
      Map<String, dynamic>.from(j['loadout'] as Map? ?? {}),
    ),
    revision: (j['revision'] as num?)?.toInt() ?? 1,
    isDefault: j['is_default'] == true,
  );
}
