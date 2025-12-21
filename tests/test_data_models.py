"""
Test suite for Dolmenwood AI DM Data Models

This file contains tests to verify that all Pydantic models
are correctly defined and functional.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime
from pydantic import ValidationError

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Import all models
from data_models import (
    # Enums
    Kindred, CharacterClass, ItemType, MagicType, TimeOfDay,
    Season, Weather, LocationType, TerrainType, QuestStatus,
    RelationshipLevel, SettlementSize, SaveType,
    # v1.1: New enums
    SourceType, ContentType, AdventureType,
    # Helpers
    generate_id, calculate_ability_modifier,
    # v1.1: Source models
    SourceReference, ContentSource,
    # Models
    Item, Spell, DolmenwoodCharacter, QuestObjective, Quest,
    WorldEvent, WorldState, Enemy, CombatState, Building,
    Settlement, HexLocation, NPC, GameRule, MonsterStatBlock,
    HistoryEntry, SessionSave,
    # v1.1: Adventure models
    AdventureLocation, AdventureModule,
)


class TestHelperFunctions:
    """Test helper functions."""
    
    def test_generate_id_without_prefix(self):
        """Test ID generation without prefix."""
        id1 = generate_id()
        id2 = generate_id()
        assert id1 != id2
        assert id1.startswith("id_")  # Default prefix
        assert len(id1) == 11  # "id_" + 8 chars
    
    def test_generate_id_with_prefix(self):
        """Test ID generation with prefix."""
        char_id = generate_id("char")
        assert char_id.startswith("char_")
        assert len(char_id) == 13  # "char_" + 8 chars
    
    def test_ability_modifier_calculation(self):
        """Test OSE ability modifier calculation."""
        assert calculate_ability_modifier(3) == -3
        assert calculate_ability_modifier(4) == -2
        assert calculate_ability_modifier(5) == -2
        assert calculate_ability_modifier(6) == -1
        assert calculate_ability_modifier(8) == -1
        assert calculate_ability_modifier(9) == 0
        assert calculate_ability_modifier(12) == 0
        assert calculate_ability_modifier(13) == 1
        assert calculate_ability_modifier(15) == 1
        assert calculate_ability_modifier(16) == 2
        assert calculate_ability_modifier(17) == 2
        assert calculate_ability_modifier(18) == 3


class TestItemModel:
    """Test Item model."""
    
    def test_basic_item_creation(self):
        """Test creating a basic item."""
        item = Item(
            name="Torch",
            type=ItemType.GEAR,
            weight=10,
            cost_sp=1,
            description="Provides light in a 30' radius"
        )
        assert item.name == "Torch"
        assert item.type == ItemType.GEAR
        assert item.weight == 10
        assert item.is_magical is False
    
    def test_weapon_creation(self):
        """Test creating a weapon."""
        sword = Item(
            name="Longsword",
            type=ItemType.WEAPON,
            weight=40,
            cost_sp=10,
            damage="1d8",
            is_melee=True,
        )
        assert sword.damage == "1d8"
        assert sword.is_melee is True
    
    def test_ranged_weapon(self):
        """Test creating a ranged weapon."""
        bow = Item(
            name="Shortbow",
            type=ItemType.WEAPON,
            weight=20,
            cost_sp=25,
            damage="1d6",
            is_melee=False,
            is_ranged=True,
            range_short=50,
            range_medium=100,
            range_long=150,
            two_handed=True,
        )
        assert bow.is_ranged is True
        assert bow.range_short == 50
    
    def test_valid_damage_notation(self):
        """Test valid damage dice notations."""
        valid_notations = ["1d6", "2d8", "1d8+1", "3d6+2", "1d4-1"]
        for notation in valid_notations:
            item = Item(name="Test", type=ItemType.WEAPON, damage=notation)
            assert item.damage == notation
    
    def test_invalid_damage_notation(self):
        """Test that invalid damage notation raises error."""
        with pytest.raises(ValidationError):
            Item(name="Test", type=ItemType.WEAPON, damage="invalid")
    
    def test_armor_creation(self):
        """Test creating armor."""
        chainmail = Item(
            name="Chainmail",
            type=ItemType.ARMOR,
            weight=400,
            cost_sp=40,
            ac_bonus=4,
        )
        assert chainmail.ac_bonus == 4


class TestSpellModel:
    """Test Spell model."""
    
    def test_spell_creation(self):
        """Test creating a spell."""
        spell = Spell(
            name="Magic Missile",
            level=1,
            school="Evocation",
            magic_type=MagicType.ARCANE,
            range="150'",
            duration="Instantaneous",
            description="Creates magical darts that automatically hit.",
        )
        assert spell.name == "Magic Missile"
        assert spell.level == 1
        assert spell.magic_type == MagicType.ARCANE
    
    def test_divine_spell(self):
        """Test creating a divine spell."""
        spell = Spell(
            name="Cure Light Wounds",
            level=1,
            school="Healing",
            magic_type=MagicType.DIVINE,
            casting_time="1 round",
            range="Touch",
            duration="Instantaneous",
            description="Heals 1d6+1 HP",
            reversible=True,
        )
        assert spell.magic_type == MagicType.DIVINE
        assert spell.reversible is True


class TestDolmenwoodCharacter:
    """Test DolmenwoodCharacter model."""
    
    @pytest.fixture
    def sample_character(self):
        """Create a sample character for testing."""
        return DolmenwoodCharacter(
            name="Aldric the Bold",
            player_name="Test Player",
            kindred=Kindred.HUMAN,
            character_class=CharacterClass.FIGHTER,
            level=3,
            strength=16,
            intelligence=10,
            wisdom=12,
            dexterity=14,
            constitution=15,
            charisma=8,
            hp_current=18,
            hp_max=22,
            ac=14,
            xp_current=4500,
            xp_next_level=8000,
        )
    
    def test_character_creation(self, sample_character):
        """Test basic character creation."""
        assert sample_character.name == "Aldric the Bold"
        assert sample_character.kindred == Kindred.HUMAN
        assert sample_character.character_class == CharacterClass.FIGHTER
        assert sample_character.level == 3
    
    def test_ability_modifiers(self, sample_character):
        """Test ability modifier properties."""
        assert sample_character.str_mod == 2  # 16 = +2
        assert sample_character.int_mod == 0  # 10 = 0
        assert sample_character.wis_mod == 0  # 12 = 0
        assert sample_character.dex_mod == 1  # 14 = +1
        assert sample_character.con_mod == 1  # 15 = +1
        assert sample_character.cha_mod == -1  # 8 = -1
    
    def test_is_alive_property(self, sample_character):
        """Test is_alive property."""
        assert sample_character.is_alive is True
        sample_character.hp_current = 0
        assert sample_character.is_alive is False
    
    def test_take_damage(self, sample_character):
        """Test damage application."""
        initial_hp = sample_character.hp_current
        damage_taken = sample_character.take_damage(5)
        assert damage_taken == 5
        assert sample_character.hp_current == initial_hp - 5
    
    def test_take_lethal_damage(self, sample_character):
        """Test lethal damage."""
        sample_character.take_damage(100)
        assert sample_character.hp_current == 0
        assert sample_character.is_alive is False
    
    def test_heal(self, sample_character):
        """Test healing."""
        sample_character.hp_current = 10
        healed = sample_character.heal(5)
        assert healed == 5
        assert sample_character.hp_current == 15
    
    def test_heal_cannot_exceed_max(self, sample_character):
        """Test that healing cannot exceed max HP."""
        sample_character.hp_current = 20
        healed = sample_character.heal(10)
        assert healed == 2  # 22 - 20 = 2
        assert sample_character.hp_current == sample_character.hp_max
    
    def test_add_xp_no_level_up(self, sample_character):
        """Test XP addition without level up."""
        leveled = sample_character.add_xp(100)
        assert leveled is False
        assert sample_character.xp_current == 4600
    
    def test_add_xp_triggers_level_up_check(self, sample_character):
        """Test XP addition triggers level up."""
        leveled = sample_character.add_xp(4000)  # 4500 + 4000 = 8500 >= 8000
        assert leveled is True
    
    def test_encumbrance(self, sample_character):
        """Test encumbrance calculation."""
        sample_character.inventory = [
            Item(name="Sword", type=ItemType.WEAPON, weight=40),
            Item(name="Shield", type=ItemType.SHIELD, weight=100),
            Item(name="Torches", type=ItemType.GEAR, weight=10, quantity=5),
        ]
        expected = 40 + 100 + (10 * 5)  # 190
        assert sample_character.encumbrance == expected
    
    def test_ability_score_validation(self):
        """Test ability score range validation."""
        with pytest.raises(ValidationError):
            DolmenwoodCharacter(
                name="Invalid",
                kindred=Kindred.HUMAN,
                character_class=CharacterClass.FIGHTER,
                strength=20,  # Invalid - max is 18
                intelligence=10,
                wisdom=10,
                dexterity=10,
                constitution=10,
                charisma=10,
                hp_current=5,
                hp_max=5,
            )
    
    def test_hp_validation(self):
        """Test HP fields allow any valid values."""
        # HP is not automatically clamped - that's application logic
        char = DolmenwoodCharacter(
            name="Test",
            kindred=Kindred.ELF,
            character_class=CharacterClass.MAGICIAN,
            strength=10, intelligence=16, wisdom=12,
            dexterity=14, constitution=10, charisma=12,
            hp_current=20,
            hp_max=10,
        )
        # Model stores what it's given - clamping is done via heal() method
        assert char.hp_current == 20
        assert char.hp_max == 10


class TestQuestModels:
    """Test Quest and QuestObjective models."""
    
    def test_quest_creation(self):
        """Test creating a quest."""
        quest = Quest(
            title="Find the Lost Artifact",
            description="An ancient artifact has been stolen from the temple.",
            giver_npc="npc_priest_001",
            objectives=[
                QuestObjective(description="Investigate the temple"),
                QuestObjective(description="Track the thieves"),
                QuestObjective(description="Retrieve the artifact"),
            ],
            rewards="500 SP, Temple's Blessing",
        )
        assert len(quest.objectives) == 3
        assert quest.status == QuestStatus.ACTIVE
    
    def test_quest_progress(self):
        """Test quest progress tracking."""
        quest = Quest(
            title="Test Quest",
            description="A test quest",
            objectives=[
                QuestObjective(description="Obj 1", completed=True),
                QuestObjective(description="Obj 2", completed=False),
                QuestObjective(description="Obj 3"),
            ],
        )
        # Progress is now a float (0.0 to 1.0)
        assert quest.progress == pytest.approx(1/3, rel=0.01)
    
    def test_quest_progress_empty(self):
        """Test quest progress with no objectives."""
        quest = Quest(
            title="Test",
            description="Test",
            objectives=[],
        )
        assert quest.progress == 0.0
    
    def test_quest_progress_all_complete(self):
        """Test quest progress when all complete."""
        quest = Quest(
            title="Test",
            description="Test",
            objectives=[
                QuestObjective(description="Obj 1", completed=True),
                QuestObjective(description="Obj 2", completed=True),
            ],
        )
        assert quest.progress == 1.0


class TestWorldState:
    """Test WorldState model."""
    
    @pytest.fixture
    def sample_world(self):
        """Create a sample world state."""
        return WorldState(
            campaign_name="The Dolmenwood Chronicles",
            current_date="15th of Grimwold, 1412",
            current_hex="0808",
            current_location_name="Prigwort",
            current_location_type=LocationType.SETTLEMENT,
        )
    
    def test_world_creation(self, sample_world):
        """Test basic world state creation."""
        assert sample_world.campaign_name == "The Dolmenwood Chronicles"
        assert sample_world.current_hex == "0808"
        assert sample_world.season == Season.SPRING  # Default is Spring
    
    def test_default_faction_standings(self, sample_world):
        """Test faction standings start empty."""
        # Faction standings are empty by default - set by application logic
        assert sample_world.faction_standings == {}
    
    def test_advance_time(self, sample_world):
        """Test time advancement."""
        sample_world.turn_count = 0
        sample_world.advance_time(6)  # 1 hour
        assert sample_world.turn_count == 6
    
    def test_time_of_day_changes(self, sample_world):
        """Test that time of day updates correctly."""
        sample_world.turn_count = 0  # Midnight
        sample_world.advance_time(36)  # 6 hours = 6 AM
        assert sample_world.time_of_day == TimeOfDay.DAWN
        
        sample_world.advance_time(6)  # +1 hour = 7 AM
        assert sample_world.time_of_day == TimeOfDay.MORNING
    
    def test_modify_faction_standing(self, sample_world):
        """Test faction standing modification."""
        new_standing = sample_world.modify_faction_standing("Cold Prince", 3)
        assert new_standing == 3
        assert sample_world.faction_standings["Cold Prince"] == 3
    
    def test_faction_standing_clamped(self, sample_world):
        """Test faction standing is clamped to -10/+10."""
        sample_world.modify_faction_standing("Cold Prince", 15)
        assert sample_world.faction_standings["Cold Prince"] == 10
        
        sample_world.modify_faction_standing("Drune", -15)
        assert sample_world.faction_standings["Drune"] == -10
    
    def test_discover_hex(self, sample_world):
        """Test hex discovery."""
        is_new = sample_world.discover_hex("0909")
        assert is_new is True
        assert "0909" in sample_world.discovered_hexes
        
        is_new = sample_world.discover_hex("0909")
        assert is_new is False  # Already discovered


class TestCombatState:
    """Test CombatState and Enemy models."""
    
    @pytest.fixture
    def sample_combat(self):
        """Create a sample combat state."""
        return CombatState(
            campaign_id="camp_test",
            is_active=True,
            round_number=1,
            party_combatants=["char_001", "char_002"],
            enemies=[
                Enemy(
                    name="Goblin 1",
                    monster_type="goblin",
                    hp_current=4,
                    hp_max=4,
                    ac=13,
                    attack_bonus=1,
                    damage="1d6",
                    morale_score=7,
                ),
                Enemy(
                    name="Goblin 2",
                    monster_type="goblin",
                    hp_current=5,
                    hp_max=5,
                    ac=13,
                    attack_bonus=1,
                    damage="1d6",
                    morale_score=7,
                ),
            ],
        )
    
    def test_combat_creation(self, sample_combat):
        """Test combat state creation."""
        assert sample_combat.is_active is True
        assert len(sample_combat.enemies) == 2
    
    def test_enemy_is_alive(self, sample_combat):
        """Test enemy is_alive property."""
        enemy = sample_combat.enemies[0]
        assert enemy.is_alive is True
        
        enemy.hp_current = 0
        assert enemy.is_alive is False
    
    def test_enemy_morale_breaks(self, sample_combat):
        """Test enemy morale breaking."""
        enemy = sample_combat.enemies[0]
        enemy.morale_broken = True
        assert enemy.is_alive is False  # Fled
    
    def test_get_active_enemies(self, sample_combat):
        """Test getting active enemies."""
        active = sample_combat.get_active_enemies()
        assert len(active) == 2
        
        sample_combat.enemies[0].hp_current = 0
        active = sample_combat.get_active_enemies()
        assert len(active) == 1
    
    def test_combat_log(self, sample_combat):
        """Test combat log entries."""
        sample_combat.add_log_entry("Combat begins!")
        assert "[R1] Combat begins!" in sample_combat.combat_log[0]
    
    def test_check_combat_end(self, sample_combat):
        """Test combat end detection."""
        assert sample_combat.check_combat_end() is None  # Ongoing
        
        # Kill all enemies
        for enemy in sample_combat.enemies:
            enemy.hp_current = 0
        assert sample_combat.check_combat_end() == "party_victory"
    
    def test_next_round(self, sample_combat):
        """Test advancing to next round."""
        sample_combat.party_initiative = 5
        sample_combat.enemy_initiative = 3
        sample_combat.next_round()
        
        assert sample_combat.round_number == 2
        assert sample_combat.party_initiative is None
        assert sample_combat.enemy_initiative is None


class TestLocationModels:
    """Test HexLocation, Settlement, and Building models."""
    
    def test_hex_location(self):
        """Test hex location creation."""
        hex_loc = HexLocation(
            hex_id="0808",
            coordinates=(8, 8),
            terrain_type=TerrainType.FOREST,
            description="Dense woodland with ancient oaks.",
            location_name="The Whispering Woods",
        )
        assert hex_loc.hex_id == "0808"
        assert hex_loc.terrain_type == TerrainType.FOREST
    
    def test_hex_visit(self):
        """Test visiting a hex."""
        hex_loc = HexLocation(
            hex_id="0909",
            coordinates=(9, 9),
            terrain_type=TerrainType.HILLS,
            description="Rolling hills",
        )
        first = hex_loc.visit()
        assert first is True
        assert hex_loc.discovered is True
        assert hex_loc.visited_count == 1
        
        second = hex_loc.visit()
        assert second is False  # Not first visit
        assert hex_loc.visited_count == 2
    
    def test_invalid_hex_id(self):
        """Test that invalid hex IDs are rejected."""
        with pytest.raises(ValidationError):
            HexLocation(
                hex_id="invalid",  # Must be 4 digits
                coordinates=(0, 0),
                terrain_type=TerrainType.FOREST,
                description="Test",
            )
    
    def test_settlement_creation(self):
        """Test settlement creation."""
        settlement = Settlement(
            name="Prigwort",
            hex_id="0808",
            size=SettlementSize.VILLAGE,
            population=450,
            has_inn=True,
            has_market=True,
            ruling_faction="Duchy of Brackenwold",
            description="A bustling village at the edge of the wood.",
        )
        assert settlement.name == "Prigwort"
        assert settlement.size == SettlementSize.VILLAGE


class TestNPCModel:
    """Test NPC model."""
    
    @pytest.fixture
    def sample_npc(self):
        """Create a sample NPC."""
        return NPC(
            name="Old Bramble",
            kindred="Human",
            occupation="Herbalist",
            personality_traits=["Suspicious", "Knowledgeable"],
            goals=["Protect the forest secrets"],
            current_location="0808",
            faction="Witches",
            relationship_party=RelationshipLevel.NEUTRAL,
        )
    
    def test_npc_creation(self, sample_npc):
        """Test NPC creation."""
        assert sample_npc.name == "Old Bramble"
        assert sample_npc.relationship_party == RelationshipLevel.NEUTRAL
    
    def test_improve_relationship(self, sample_npc):
        """Test improving relationship."""
        new_level = sample_npc.improve_relationship()
        assert new_level == RelationshipLevel.FRIENDLY
        
        new_level = sample_npc.improve_relationship()
        assert new_level == RelationshipLevel.ALLIED
        
        # Can't go higher than allied
        new_level = sample_npc.improve_relationship()
        assert new_level == RelationshipLevel.ALLIED
    
    def test_worsen_relationship(self, sample_npc):
        """Test worsening relationship."""
        new_level = sample_npc.worsen_relationship()
        assert new_level == RelationshipLevel.UNFRIENDLY
        
        new_level = sample_npc.worsen_relationship()
        assert new_level == RelationshipLevel.HOSTILE
        
        # Can't go lower than hostile
        new_level = sample_npc.worsen_relationship()
        assert new_level == RelationshipLevel.HOSTILE


class TestMonsterStatBlock:
    """Test MonsterStatBlock model."""
    
    def test_monster_creation(self):
        """Test monster stat block creation."""
        goblin = MonsterStatBlock(
            name="Goblin",
            armor_class=13,
            hit_dice="1-1",
            movement="60' (20')",
            attacks=["1 × weapon (1d6)"],
            damage=["1d6"],
            saves_as="Fighter 1",
            morale=7,
            alignment="Chaotic",
            description="Small, cruel humanoids",
            number_appearing="2d4",
            xp_value=5,
        )
        assert goblin.name == "Goblin"
        assert goblin.morale == 7
    
    def test_roll_hp(self):
        """Test HP rolling."""
        monster = MonsterStatBlock(
            name="Test Monster",
            armor_class=10,
            hit_dice="3+1",  # 3d8+1
            movement="90' (30')",
            saves_as="Fighter 3",
            morale=8,
            description="Test",
            number_appearing="1",
        )
        
        # Roll several times and check range
        for _ in range(10):
            hp = monster.roll_hp()
            assert hp >= 1  # Minimum 1
            assert hp <= 25  # Max 3*8+1 = 25


class TestGameRule:
    """Test GameRule model."""
    
    def test_rule_creation(self):
        """Test game rule creation."""
        rule = GameRule(
            category="combat",
            subcategory="initiative",
            title="Initiative",
            content="Each side rolls 1d6. The side with the higher roll acts first.",
            page_reference="OSE Core p.120",
            examples=["Party rolls 5, goblins roll 3. Party acts first."],
        )
        assert rule.category == "combat"
        assert "1d6" in rule.content


class TestIntegration:
    """Integration tests combining multiple models."""
    
    def test_full_character_with_gear(self):
        """Test character with full equipment."""
        sword = Item(
            name="Longsword +1",
            type=ItemType.WEAPON,
            damage="1d8",
            is_magical=True,
            magical_properties="+1 to attack and damage",
        )
        
        armor = Item(
            name="Chainmail",
            type=ItemType.ARMOR,
            ac_bonus=4,
        )
        
        spell = Spell(
            name="Sleep",
            level=1,
            magic_type=MagicType.ARCANE,
            description="Causes creatures to fall into magical slumber.",
        )
        
        char = DolmenwoodCharacter(
            name="Elara Starweaver",
            kindred=Kindred.ELF,
            character_class=CharacterClass.MAGICIAN,
            strength=10,
            intelligence=16,
            wisdom=12,
            dexterity=14,
            constitution=10,
            charisma=12,
            hp_current=6,
            hp_max=6,
            ac=10,
            inventory=[sword, armor],
            equipped_weapon=sword,
            equipped_armor=armor,
            spells_known=[spell],
            spells_memorized=[spell],
            spell_slots={1: 2},
        )
        
        assert char.equipped_weapon.name == "Longsword +1"
        assert len(char.spells_memorized) == 1
    
    def test_campaign_setup(self):
        """Test setting up a full campaign."""
        # Create world
        world = WorldState(
            campaign_name="The Lost Temple",
            current_hex="0808",
            current_location_name="Prigwort",
            current_location_type=LocationType.SETTLEMENT,
        )
        
        # Create character
        char = DolmenwoodCharacter(
            name="Bram Blackwood",
            kindred=Kindred.HUMAN,
            character_class=CharacterClass.FIGHTER,
            strength=16, intelligence=10, wisdom=10,
            dexterity=12, constitution=14, charisma=10,
            hp_current=8, hp_max=8,
        )
        
        # Add character to party
        world.party_characters.append(char.character_id)
        
        # Create a quest
        quest = Quest(
            title="Clear the Old Mill",
            description="Goblins have taken over the abandoned mill.",
            objectives=[
                QuestObjective(description="Travel to the old mill"),
                QuestObjective(description="Defeat the goblins"),
                QuestObjective(description="Return to the village elder"),
            ],
        )
        world.active_quests.append(quest)
        
        # Verify
        assert len(world.party_characters) == 1
        assert len(world.active_quests) == 1
        assert world.active_quests[0].title == "Clear the Old Mill"


def run_demo():
    """Run a quick demonstration of the data models."""
    print("=" * 60)
    print("DOLMENWOOD AI DM - DATA MODELS DEMONSTRATION")
    print("=" * 60)
    
    # Create a character
    print("\n1. Creating a character...")
    char = DolmenwoodCharacter(
        name="Thornwick Bramblefur",
        player_name="Demo Player",
        kindred=Kindred.BREGGLE,
        character_class=CharacterClass.KNIGHT,
        level=2,
        strength=14,
        intelligence=10,
        wisdom=12,
        dexterity=10,
        constitution=16,
        charisma=14,
        hp_current=14,
        hp_max=14,
        ac=16,
        xp_current=2500,
        xp_next_level=4000,
    )
    print(f"   Created: {char.name} - {char.kindred.value} {char.character_class.value} Level {char.level}")
    print(f"   HP: {char.hp_current}/{char.hp_max}, AC: {char.ac}")
    print(f"   STR: {char.strength} ({char.str_mod:+d}), CON: {char.constitution} ({char.con_mod:+d})")
    
    # Create world state
    print("\n2. Creating world state...")
    world = WorldState(
        campaign_name="The Brackenwold Chronicles",
        current_date="3rd of Woldsmoon, 1412",
        current_hex="0808",
        current_location_name="Prigwort",
        current_location_type=LocationType.SETTLEMENT,
        season=Season.AUTUMN,
        weather=Weather.FOG,
    )
    world.party_characters.append(char.character_id)
    print(f"   Campaign: {world.campaign_name}")
    print(f"   Location: Hex {world.current_hex} - {world.current_location_name}")
    print(f"   Conditions: {world.weather.value}, {world.season.value}, {world.time_of_day.value}")
    
    # Create an NPC
    print("\n3. Creating an NPC...")
    npc = NPC(
        name="Elder Mosspocket",
        kindred="Mossling",
        occupation="Village Elder",
        personality_traits=["Wise", "Cautious", "Helpful"],
        goals=["Protect Prigwort", "Maintain peace with the forest"],
        current_location="0808",
        faction="Duchy of Brackenwold",
        relationship_party=RelationshipLevel.FRIENDLY,
    )
    print(f"   Created: {npc.name} ({npc.kindred} {npc.occupation})")
    print(f"   Relationship: {npc.relationship_party.value}")
    
    # Create a quest
    print("\n4. Creating a quest...")
    quest = Quest(
        title="The Whispering Stones",
        description="Strange lights have been seen near the old standing stones.",
        giver_npc=npc.npc_id,
        objectives=[
            QuestObjective(description="Investigate the standing stones at night"),
            QuestObjective(description="Discover the source of the lights"),
            QuestObjective(description="Report findings to Elder Mosspocket"),
        ],
        rewards="50 SP, Elder's gratitude",
    )
    world.active_quests.append(quest)
    completed = sum(1 for obj in quest.objectives if obj.completed)
    total = len(quest.objectives)
    print(f"   Quest: {quest.title}")
    print(f"   Progress: {completed}/{total} objectives")
    
    # Simulate combat
    print("\n5. Creating a combat encounter...")
    combat = CombatState(
        campaign_id=world.campaign_id,
        is_active=True,
        round_number=1,
        party_combatants=[char.character_id],
        enemies=[
            Enemy(name="Goblin Scout", monster_type="goblin", hp_current=4, hp_max=4, ac=13, morale_score=6),
            Enemy(name="Goblin Warrior", monster_type="goblin", hp_current=6, hp_max=6, ac=14, morale_score=7),
        ],
        environment="Forest clearing, dappled moonlight",
    )
    print(f"   Combat started: {len(combat.party_combatants)} vs {len(combat.enemies)}")
    print(f"   Enemies: {', '.join(e.name for e in combat.enemies)}")
    
    # Simulate some combat
    print("\n6. Simulating combat...")
    combat.add_log_entry(f"{char.name} attacks Goblin Scout!")
    combat.enemies[0].take_damage(5)
    combat.add_log_entry("Goblin Scout is slain!")
    print(f"   Active enemies: {len(combat.get_active_enemies())}")
    print(f"   Combat log: {combat.combat_log[-1]}")
    
    print("\n" + "=" * 60)
    print("DEMONSTRATION COMPLETE")
    print("=" * 60)
    print("\nAll data models are working correctly!")


# =============================================================================
# v1.1: SOURCE TRACKING TESTS
# =============================================================================

class TestSourceTracking:
    """Tests for v1.1 source tracking models."""
    
    def test_source_type_enum(self):
        """Test SourceType enum values."""
        assert SourceType.CORE_RULEBOOK.value == "core_rulebook"
        assert SourceType.CAMPAIGN_SETTING.value == "campaign_setting"
        assert SourceType.ADVENTURE_MODULE.value == "adventure_module"
        assert SourceType.HOMEBREW.value == "homebrew"
    
    def test_content_type_enum(self):
        """Test ContentType enum values."""
        assert ContentType.CORE_RULE.value == "core_rule"
        assert ContentType.MONSTER_STAT.value == "monster_stat"
        assert ContentType.ADVENTURE_CONTENT.value == "adventure_content"
    
    def test_source_reference_creation(self):
        """Test creating a SourceReference."""
        ref = SourceReference(
            source_id="players_book",
            book_code="players_book",
            page_reference="p. 42",
            section="Combat"
        )
        
        assert ref.source_id == "players_book"
        assert ref.page_reference == "p. 42"
    
    def test_source_reference_minimal(self):
        """Test SourceReference with only required fields."""
        ref = SourceReference(
            source_id="monster_book",
            book_code="monster_book"
        )
        
        assert ref.page_reference is None
        assert ref.section is None
    
    def test_content_source_creation(self):
        """Test creating a ContentSource."""
        source = ContentSource(
            source_id="players_book",
            source_type=SourceType.CORE_RULEBOOK,
            book_name="Dolmenwood Player's Book",
            book_code="players_book",
            file_path="/path/to/players.pdf",
            version="1.0"
        )
        
        assert source.source_id == "players_book"
        assert source.source_type == SourceType.CORE_RULEBOOK
        assert source.publisher == "Necrotic Gnome"  # Default
    
    def test_content_source_priority(self):
        """Test ContentSource priority calculation."""
        core = ContentSource(
            source_id="core",
            source_type=SourceType.CORE_RULEBOOK,
            book_name="Core Book",
            book_code="core",
            file_path="/core.pdf"
        )
        
        adventure = ContentSource(
            source_id="adv",
            source_type=SourceType.ADVENTURE_MODULE,
            book_name="Adventure",
            book_code="adv",
            file_path="/adv.pdf"
        )
        
        homebrew = ContentSource(
            source_id="home",
            source_type=SourceType.HOMEBREW,
            book_name="Homebrew",
            book_code="home",
            file_path="/home.pdf"
        )
        
        assert core.get_priority() < adventure.get_priority()
        assert adventure.get_priority() < homebrew.get_priority()
    
    def test_item_with_source(self):
        """Test Item with source reference."""
        source_ref = SourceReference(
            source_id="players_book",
            book_code="players_book",
            page_reference="p. 55"
        )
        
        item = Item(
            name="Long Sword",
            type=ItemType.WEAPON,
            damage="1d8",
            cost_sp=100,
            source=source_ref
        )
        
        assert item.source is not None
        assert item.source.source_id == "players_book"
    
    def test_spell_with_source(self):
        """Test Spell with source reference."""
        source_ref = SourceReference(
            source_id="players_book",
            book_code="players_book",
            page_reference="p. 120"
        )
        
        spell = Spell(
            name="Magic Missile",
            level=1,
            magic_type=MagicType.ARCANE,
            description="Launches magical projectiles",
            source=source_ref
        )
        
        assert spell.source is not None
        assert spell.source.page_reference == "p. 120"
    
    def test_game_rule_with_source(self):
        """Test GameRule with v1.1 fields."""
        source_ref = SourceReference(
            source_id="players_book",
            book_code="players_book",
            page_reference="p. 42"
        )
        
        rule = GameRule(
            category="combat",
            title="Initiative",
            content="Each side rolls 1d6 for initiative.",
            source=source_ref,
            content_type=ContentType.CORE_RULE,
            tags=["initiative", "combat", "d6"]
        )
        
        assert rule.source is not None
        assert rule.content_type == ContentType.CORE_RULE
        assert "initiative" in rule.tags
        assert rule.version == "1.0"
    
    def test_monster_with_source_and_variant(self):
        """Test MonsterStatBlock with v1.1 fields."""
        source_ref = SourceReference(
            source_id="monster_book",
            book_code="monster_book",
            page_reference="p. 50"
        )
        
        # Base monster
        goblin = MonsterStatBlock(
            name="Goblin",
            armor_class=13,
            hit_dice="1-1",
            movement="60' (20')",
            saves_as="F1",
            morale=7,
            number_appearing="2d4",
            description="Small, wicked humanoids",
            source=source_ref
        )
        
        # Variant
        goblin_chief = MonsterStatBlock(
            name="Goblin Chief",
            armor_class=14,
            hit_dice="3",
            movement="60' (20')",
            saves_as="F3",
            morale=9,
            number_appearing="1",
            description="Leader of goblins",
            source=source_ref,
            is_variant=True,
            base_monster_id=goblin.monster_id
        )
        
        assert goblin.is_variant is False
        assert goblin_chief.is_variant is True
        assert goblin_chief.base_monster_id == goblin.monster_id
    
    def test_npc_with_source(self):
        """Test NPC with source reference."""
        source_ref = SourceReference(
            source_id="campaign_book",
            book_code="campaign_book",
            page_reference="p. 88"
        )
        
        npc = NPC(
            name="Old Barnaby",
            kindred="Human",
            occupation="Innkeeper",
            description="A weathered old man",
            source=source_ref
        )
        
        assert npc.source is not None
        assert npc.source.source_id == "campaign_book"


# =============================================================================
# v1.1: ADVENTURE MODULE TESTS
# =============================================================================

class TestAdventureModels:
    """Tests for v1.1 adventure content models."""
    
    def test_adventure_type_enum(self):
        """Test AdventureType enum values."""
        assert AdventureType.DUNGEON_CRAWL.value == "dungeon_crawl"
        assert AdventureType.WILDERNESS.value == "wilderness"
        assert AdventureType.URBAN.value == "urban"
    
    def test_adventure_location_creation(self):
        """Test creating an AdventureLocation."""
        source_ref = SourceReference(
            source_id="fungal_tomb",
            book_code="fungal_tomb",
            page_reference="p. 5"
        )
        
        location = AdventureLocation(
            adventure_id="fungal_tomb",
            name="Room 1: Entrance Hall",
            short_name="Entrance Hall",
            number="1",
            read_aloud_text="You enter a dark chamber...",
            dm_notes="The door is trapped.",
            dimensions="30' × 40'",
            lighting="Dark",
            features=["stone door", "fallen pillars"],
            creatures=["goblin_1", "goblin_2"],
            exits={"north": "room_2", "east": "room_3"},
            source=source_ref
        )
        
        assert location.adventure_id == "fungal_tomb"
        assert location.number == "1"
        assert location.visited is False
        assert "north" in location.exits
    
    def test_adventure_location_state(self):
        """Test AdventureLocation state tracking."""
        location = AdventureLocation(
            adventure_id="test_adv",
            name="Test Room",
            short_name="Test"
        )
        
        assert location.visited is False
        assert location.looted is False
        assert location.creatures_defeated is False
        
        # Simulate progress
        location.visited = True
        location.creatures_defeated = True
        
        assert location.visited is True
        assert location.creatures_defeated is True
    
    def test_adventure_module_creation(self):
        """Test creating an AdventureModule."""
        source = ContentSource(
            source_id="fungal_tomb",
            source_type=SourceType.ADVENTURE_MODULE,
            book_name="The Fungal Tomb",
            book_code="fungal_tomb",
            file_path="/adventures/fungal_tomb.pdf"
        )
        
        adventure = AdventureModule(
            title="The Fungal Tomb",
            subtitle="A Dolmenwood Adventure",
            recommended_levels="1-3",
            estimated_sessions=2,
            adventure_type=AdventureType.DUNGEON_CRAWL,
            locations=["loc_1", "loc_2", "loc_3"],
            starting_location="loc_1",
            hook="A villager has gone missing in the old barrow.",
            synopsis="Investigate the barrow and discover its fungal horrors.",
            conclusion="Defeat the fungal king or flee the tomb.",
            total_xp=500,
            major_treasure=["Staff of Spores", "200 SP"],
            source=source,
            recommended_hex="0812"
        )
        
        assert adventure.title == "The Fungal Tomb"
        assert adventure.adventure_type == AdventureType.DUNGEON_CRAWL
        assert len(adventure.locations) == 3
        assert adventure.recommended_hex == "0812"
    
    def test_world_state_with_adventure(self):
        """Test WorldState with v1.1 adventure tracking."""
        world = WorldState(
            campaign_name="Test Campaign",
            active_adventure="fungal_tomb",
            adventure_progress={
                "rooms_visited": ["loc_1", "loc_2"],
                "treasures_found": 3,
                "npcs_rescued": 1
            }
        )
        
        assert world.active_adventure == "fungal_tomb"
        assert world.adventure_progress["rooms_visited"] == ["loc_1", "loc_2"]
        assert world.adventure_progress["treasures_found"] == 3
    
    def test_quest_with_source(self):
        """Test Quest with source reference."""
        source_ref = SourceReference(
            source_id="fungal_tomb",
            book_code="fungal_tomb",
            page_reference="p. 3"
        )
        
        quest = Quest(
            title="Find the Missing Villager",
            description="Locate and rescue the missing farmer.",
            source=source_ref,
            objectives=[
                QuestObjective(description="Enter the barrow"),
                QuestObjective(description="Find clues about the farmer"),
                QuestObjective(description="Rescue or avenge the farmer")
            ]
        )
        
        assert quest.source is not None
        assert quest.source.source_id == "fungal_tomb"


if __name__ == "__main__":
    # Run the demo
    run_demo()
    
    # Run tests if pytest is available
    print("\n\nRunning tests with pytest...")
    pytest.main([__file__, "-v", "--tb=short"])
