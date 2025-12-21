"""
Test suite for Dolmenwood AI DM Game State Manager

This file contains tests for the SQLite-based state persistence system.
"""

import os
import tempfile
import pytest
from datetime import datetime

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from data_models import (
    DolmenwoodCharacter, Kindred, CharacterClass,
    WorldState, LocationType, Season, Weather, TimeOfDay,
    CombatState, Enemy,
    NPC, RelationshipLevel,
    HexLocation, TerrainType,
    Quest, QuestObjective, QuestStatus,
    Item, ItemType,
    Spell, MagicType,
    MonsterStatBlock,
    GameRule,
)
from game_state.state_manager import GameStateManager, DatabaseError


class TestGameStateManager:
    """Test the GameStateManager class."""
    
    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        yield db_path
        
        # Cleanup
        if os.path.exists(db_path):
            os.unlink(db_path)
    
    @pytest.fixture
    def manager(self, temp_db):
        """Create a manager with temporary database."""
        mgr = GameStateManager(temp_db)
        yield mgr
        mgr.close()
    
    @pytest.fixture
    def sample_character(self):
        """Create a sample character."""
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
    
    @pytest.fixture
    def sample_world(self):
        """Create a sample world state."""
        return WorldState(
            campaign_name="The Brackenwold Chronicles",
            current_date="3rd of Woldsmoon, 1412",
            current_hex="0808",
            current_location_name="Prigwort",
            current_location_type=LocationType.SETTLEMENT,
            season=Season.AUTUMN,
            weather=Weather.CLEAR,
        )


class TestCharacterOperations(TestGameStateManager):
    """Test character CRUD operations."""
    
    def test_create_character(self, manager, sample_character):
        """Test creating a character."""
        char_id = manager.create_character(sample_character)
        assert char_id == sample_character.character_id
    
    def test_get_character(self, manager, sample_character):
        """Test retrieving a character."""
        manager.create_character(sample_character)
        loaded = manager.get_character(sample_character.character_id)
        
        assert loaded is not None
        assert loaded.name == sample_character.name
        assert loaded.strength == sample_character.strength
        assert loaded.hp_current == sample_character.hp_current
    
    def test_get_nonexistent_character(self, manager):
        """Test retrieving a character that doesn't exist."""
        loaded = manager.get_character("nonexistent_id")
        assert loaded is None
    
    def test_update_character(self, manager, sample_character):
        """Test updating a character."""
        manager.create_character(sample_character)
        
        sample_character.hp_current = 10
        sample_character.xp_current = 5000
        success = manager.update_character(sample_character)
        
        assert success is True
        
        loaded = manager.get_character(sample_character.character_id)
        assert loaded.hp_current == 10
        assert loaded.xp_current == 5000
    
    def test_delete_character(self, manager, sample_character):
        """Test deleting a character."""
        manager.create_character(sample_character)
        success = manager.delete_character(sample_character.character_id)
        
        assert success is True
        assert manager.get_character(sample_character.character_id) is None
    
    def test_list_characters(self, manager, sample_character):
        """Test listing all characters."""
        manager.create_character(sample_character)
        
        # Create another character
        char2 = DolmenwoodCharacter(
            name="Elara Starweaver",
            kindred=Kindred.ELF,
            character_class=CharacterClass.MAGICIAN,
            strength=8, intelligence=16, wisdom=14,
            dexterity=12, constitution=10, charisma=14,
            hp_current=4, hp_max=4,
        )
        manager.create_character(char2)
        
        characters = manager.list_characters()
        assert len(characters) == 2
        names = [c.name for c in characters]
        assert "Aldric the Bold" in names
        assert "Elara Starweaver" in names
    
    def test_duplicate_character_raises_error(self, manager, sample_character):
        """Test that creating duplicate character raises error."""
        manager.create_character(sample_character)
        
        with pytest.raises(DatabaseError):
            manager.create_character(sample_character)


class TestCampaignOperations(TestGameStateManager):
    """Test campaign/world state operations."""
    
    def test_create_campaign(self, manager, sample_world):
        """Test creating a campaign."""
        campaign_id = manager.create_campaign(sample_world)
        assert campaign_id == sample_world.campaign_id
    
    def test_get_world_state(self, manager, sample_world):
        """Test retrieving world state."""
        manager.create_campaign(sample_world)
        loaded = manager.get_world_state(sample_world.campaign_id)
        
        assert loaded is not None
        assert loaded.campaign_name == sample_world.campaign_name
        assert loaded.current_hex == "0808"
        assert loaded.season == Season.AUTUMN
    
    def test_update_world_state(self, manager, sample_world):
        """Test updating world state."""
        manager.create_campaign(sample_world)
        
        sample_world.turn_count = 50
        sample_world.weather = Weather.RAIN
        sample_world.discover_hex("0909")
        
        success = manager.update_world_state(sample_world)
        assert success is True
        
        loaded = manager.get_world_state(sample_world.campaign_id)
        assert loaded.turn_count == 50
        assert loaded.weather == Weather.RAIN
        assert "0909" in loaded.discovered_hexes
    
    def test_list_campaigns(self, manager, sample_world):
        """Test listing campaigns."""
        manager.create_campaign(sample_world)
        
        world2 = WorldState(campaign_name="Another Adventure")
        manager.create_campaign(world2)
        
        campaigns = manager.list_campaigns()
        assert len(campaigns) == 2
    
    def test_delete_campaign_cascade(self, manager, sample_world, sample_character):
        """Test deleting a campaign with cascade."""
        manager.create_campaign(sample_world)
        manager.create_character(sample_character, sample_world.campaign_id)
        
        success = manager.delete_campaign(sample_world.campaign_id, cascade=True)
        assert success is True
        
        # Verify cascade deletion
        assert manager.get_world_state(sample_world.campaign_id) is None


class TestCombatOperations(TestGameStateManager):
    """Test combat state operations."""
    
    @pytest.fixture
    def sample_combat(self, sample_world):
        """Create a sample combat state."""
        return CombatState(
            campaign_id=sample_world.campaign_id,
            is_active=True,
            round_number=1,
            party_combatants=["char_001"],
            enemies=[
                Enemy(
                    name="Goblin 1",
                    monster_type="goblin",
                    hp_current=4,
                    hp_max=4,
                    ac=13,
                    morale_score=7,
                ),
                Enemy(
                    name="Goblin 2",
                    monster_type="goblin",
                    hp_current=5,
                    hp_max=5,
                    ac=13,
                    morale_score=7,
                ),
            ],
        )
    
    def test_start_combat(self, manager, sample_world, sample_combat):
        """Test starting a combat."""
        manager.create_campaign(sample_world)
        combat_id = manager.start_combat(sample_combat)
        
        assert combat_id == sample_combat.combat_id
    
    def test_get_combat_state(self, manager, sample_world, sample_combat):
        """Test retrieving combat state."""
        manager.create_campaign(sample_world)
        manager.start_combat(sample_combat)
        
        loaded = manager.get_combat_state(sample_combat.combat_id)
        assert loaded is not None
        assert len(loaded.enemies) == 2
        assert loaded.is_active is True
    
    def test_get_active_combat(self, manager, sample_world, sample_combat):
        """Test getting active combat."""
        manager.create_campaign(sample_world)
        manager.start_combat(sample_combat)
        
        active = manager.get_active_combat(sample_world.campaign_id)
        assert active is not None
        assert active.combat_id == sample_combat.combat_id
    
    def test_update_combat_state(self, manager, sample_world, sample_combat):
        """Test updating combat state."""
        manager.create_campaign(sample_world)
        manager.start_combat(sample_combat)
        
        sample_combat.round_number = 3
        sample_combat.enemies[0].hp_current = 0
        manager.update_combat_state(sample_combat)
        
        loaded = manager.get_combat_state(sample_combat.combat_id)
        assert loaded.round_number == 3
        assert loaded.enemies[0].hp_current == 0
    
    def test_end_combat(self, manager, sample_world, sample_combat):
        """Test ending a combat."""
        manager.create_campaign(sample_world)
        manager.start_combat(sample_combat)
        
        success = manager.end_combat(sample_combat.combat_id)
        assert success is True
        
        # Should no longer show as active
        active = manager.get_active_combat(sample_world.campaign_id)
        assert active is None


class TestHistoryLogging(TestGameStateManager):
    """Test history logging operations."""
    
    def test_log_history(self, manager, sample_world):
        """Test logging a history entry."""
        manager.create_campaign(sample_world)
        
        entry_id = manager.log_history(
            campaign_id=sample_world.campaign_id,
            turn_number=1,
            event_type="action",
            player_input="I search the room",
            dm_response="You find a hidden door behind the bookcase.",
            state_changes={"discovered_location": "secret_passage"},
        )
        
        assert entry_id.startswith("hist_")
    
    def test_get_recent_history(self, manager, sample_world):
        """Test retrieving recent history."""
        manager.create_campaign(sample_world)
        
        # Log multiple entries
        for i in range(5):
            manager.log_history(
                campaign_id=sample_world.campaign_id,
                turn_number=i,
                event_type="action",
                player_input=f"Action {i}",
                dm_response=f"Response {i}",
            )
        
        history = manager.get_recent_history(sample_world.campaign_id, limit=3)
        assert len(history) == 3
        # Should be in reverse order (most recent first)
        assert history[0].turn_number == 4
    
    def test_get_history_by_type(self, manager, sample_world):
        """Test filtering history by event type."""
        manager.create_campaign(sample_world)
        
        manager.log_history(
            campaign_id=sample_world.campaign_id,
            turn_number=1,
            event_type="action",
            player_input="Search",
        )
        manager.log_history(
            campaign_id=sample_world.campaign_id,
            turn_number=2,
            event_type="combat",
            player_input="Attack",
        )
        manager.log_history(
            campaign_id=sample_world.campaign_id,
            turn_number=3,
            event_type="action",
            player_input="Move",
        )
        
        combat_history = manager.get_history_by_type(
            sample_world.campaign_id, 
            "combat"
        )
        assert len(combat_history) == 1
        assert combat_history[0].player_input == "Attack"


class TestSessionSaveLoad(TestGameStateManager):
    """Test session save/load operations."""
    
    def test_save_session(self, manager, sample_world, sample_character):
        """Test saving a session."""
        manager.create_campaign(sample_world)
        sample_world.party_characters.append(sample_character.character_id)
        manager.update_world_state(sample_world)
        manager.create_character(sample_character, sample_world.campaign_id)
        
        save_id = manager.save_session(
            sample_world.campaign_id,
            "Before the Dragon Fight",
            "About to enter the dragon's lair"
        )
        
        assert save_id.startswith("save_")
    
    def test_load_session(self, manager, sample_world, sample_character):
        """Test loading a session."""
        manager.create_campaign(sample_world)
        sample_world.party_characters.append(sample_character.character_id)
        manager.update_world_state(sample_world)
        manager.create_character(sample_character, sample_world.campaign_id)
        
        save_id = manager.save_session(sample_world.campaign_id, "Test Save")
        
        loaded = manager.load_session(save_id)
        assert loaded is not None
        assert loaded["save_name"] == "Test Save"
        assert "world_state" in loaded["data"]
        assert "characters" in loaded["data"]
    
    def test_restore_session(self, manager, sample_world, sample_character):
        """Test restoring a session."""
        manager.create_campaign(sample_world)
        sample_world.party_characters.append(sample_character.character_id)
        manager.update_world_state(sample_world)
        manager.create_character(sample_character, sample_world.campaign_id)
        
        # Save original state
        original_hp = sample_character.hp_current
        save_id = manager.save_session(sample_world.campaign_id, "Checkpoint")
        
        # Modify state
        sample_character.hp_current = 1
        manager.update_character(sample_character)
        
        sample_world.turn_count = 100
        manager.update_world_state(sample_world)
        
        # Restore
        success = manager.restore_session(save_id)
        assert success is True
        
        # Verify restoration
        loaded_world = manager.get_world_state(sample_world.campaign_id)
        loaded_char = manager.get_character(sample_character.character_id)
        
        assert loaded_char.hp_current == original_hp
    
    def test_list_saves(self, manager, sample_world):
        """Test listing saves."""
        manager.create_campaign(sample_world)
        
        manager.save_session(sample_world.campaign_id, "Save 1")
        manager.save_session(sample_world.campaign_id, "Save 2")
        
        saves = manager.list_saves(sample_world.campaign_id)
        assert len(saves) == 2


class TestReferenceData(TestGameStateManager):
    """Test reference data operations (monsters, items, spells, rules)."""
    
    def test_save_and_get_monster(self, manager):
        """Test monster save/load."""
        goblin = MonsterStatBlock(
            name="Goblin",
            armor_class=13,
            hit_dice="1-1",
            movement="60' (20')",
            attacks=["1 × weapon (1d6)"],
            damage=["1d6"],
            saves_as="Fighter 1",
            morale=7,
            description="Small cruel humanoid",
            number_appearing="2d4",
        )
        
        manager.save_monster(goblin)
        loaded = manager.get_monster(goblin.monster_id)
        
        assert loaded is not None
        assert loaded.name == "Goblin"
        assert loaded.morale == 7
    
    def test_search_monsters(self, manager):
        """Test monster search."""
        manager.save_monster(MonsterStatBlock(
            name="Goblin", armor_class=13, hit_dice="1-1",
            movement="60'", saves_as="F1", morale=7,
            description="", number_appearing="1d6"
        ))
        manager.save_monster(MonsterStatBlock(
            name="Hobgoblin", armor_class=14, hit_dice="1+1",
            movement="90'", saves_as="F1", morale=8,
            description="", number_appearing="1d6"
        ))
        manager.save_monster(MonsterStatBlock(
            name="Ogre", armor_class=14, hit_dice="4+1",
            movement="90'", saves_as="F4", morale=10,
            description="", number_appearing="1d6"
        ))
        
        results = manager.search_monsters("goblin")
        assert len(results) == 2  # Goblin and Hobgoblin
    
    def test_save_and_get_item(self, manager):
        """Test item save/load."""
        sword = Item(
            name="Longsword",
            type=ItemType.WEAPON,
            weight=40,
            cost_sp=10,
            damage="1d8",
        )
        
        manager.save_item(sword)
        loaded = manager.get_item(sword.item_id)
        
        assert loaded is not None
        assert loaded.name == "Longsword"
        assert loaded.damage == "1d8"
    
    def test_save_and_get_spell(self, manager):
        """Test spell save/load."""
        spell = Spell(
            name="Magic Missile",
            level=1,
            magic_type=MagicType.ARCANE,
            description="Creates magical darts",
        )
        
        manager.save_spell(spell)
        loaded = manager.get_spell(spell.spell_id)
        
        assert loaded is not None
        assert loaded.name == "Magic Missile"
        assert loaded.level == 1
    
    def test_list_spells_filtered(self, manager):
        """Test listing spells with filters."""
        manager.save_spell(Spell(
            name="Magic Missile", level=1,
            magic_type=MagicType.ARCANE, description=""
        ))
        manager.save_spell(Spell(
            name="Cure Light Wounds", level=1,
            magic_type=MagicType.DIVINE, description=""
        ))
        manager.save_spell(Spell(
            name="Fireball", level=3,
            magic_type=MagicType.ARCANE, description=""
        ))
        
        arcane_spells = manager.list_spells(magic_type="arcane")
        assert len(arcane_spells) == 2
        
        level_1_spells = manager.list_spells(level=1)
        assert len(level_1_spells) == 2
    
    def test_save_and_get_rule(self, manager):
        """Test rule save/load."""
        rule = GameRule(
            category="combat",
            title="Initiative",
            content="Each side rolls 1d6 for initiative.",
        )
        
        manager.save_rule(rule)
        loaded = manager.get_rule(rule.rule_id)
        
        assert loaded is not None
        assert loaded.title == "Initiative"


class TestFoundryExport(TestGameStateManager):
    """Test Foundry VTT export functionality."""
    
    def test_export_for_foundry(self, manager, sample_world, sample_character):
        """Test Foundry export."""
        manager.create_campaign(sample_world)
        sample_world.party_characters.append(sample_character.character_id)
        manager.update_world_state(sample_world)
        manager.create_character(sample_character, sample_world.campaign_id)
        
        export = manager.export_for_foundry(sample_world.campaign_id)
        
        assert export["system"] == "ose"
        assert len(export["actors"]) >= 1
        
        # Check character export format
        char_export = export["actors"][0]
        assert char_export["name"] == "Aldric the Bold"
        assert "system" in char_export
        assert char_export["system"]["abilities"]["str"]["value"] == 16


class TestContextManager(TestGameStateManager):
    """Test context manager functionality."""
    
    def test_context_manager(self, temp_db):
        """Test using manager as context manager."""
        with GameStateManager(temp_db) as manager:
            world = WorldState(campaign_name="Test")
            manager.create_campaign(world)
            
            # Verify data is accessible
            loaded = manager.get_world_state(world.campaign_id)
            assert loaded is not None
        
        # After context exit, should be closed
        # Can create a new manager to verify data persisted
        with GameStateManager(temp_db) as manager2:
            loaded = manager2.get_world_state(world.campaign_id)
            assert loaded is not None


def run_demo():
    """Run a demonstration of the Game State Manager."""
    import tempfile
    
    print("=" * 60)
    print("GAME STATE MANAGER DEMONSTRATION")
    print("=" * 60)
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    try:
        with GameStateManager(db_path) as manager:
            # Create a campaign
            print("\n1. Creating a campaign...")
            world = WorldState(
                campaign_name="The Lost Temple of Ylgur",
                current_date="1st of Harvestmoon, 1412",
                current_hex="0808",
                current_location_name="Prigwort",
                current_location_type=LocationType.SETTLEMENT,
            )
            manager.create_campaign(world)
            print(f"   Created: {world.campaign_name}")
            
            # Create characters
            print("\n2. Creating characters...")
            fighter = DolmenwoodCharacter(
                name="Bram Oakenshield",
                kindred=Kindred.HUMAN,
                character_class=CharacterClass.FIGHTER,
                strength=16, intelligence=10, wisdom=12,
                dexterity=14, constitution=15, charisma=10,
                hp_current=10, hp_max=10,
            )
            manager.create_character(fighter, world.campaign_id)
            
            mage = DolmenwoodCharacter(
                name="Elara Moonwhisper",
                kindred=Kindred.ELF,
                character_class=CharacterClass.MAGICIAN,
                strength=8, intelligence=17, wisdom=14,
                dexterity=12, constitution=10, charisma=13,
                hp_current=4, hp_max=4,
            )
            manager.create_character(mage, world.campaign_id)
            
            # Add to party
            world.party_characters = [fighter.character_id, mage.character_id]
            manager.update_world_state(world)
            
            characters = manager.list_characters(world.campaign_id)
            print(f"   Created {len(characters)} characters")
            for c in characters:
                print(f"   - {c.name}: {c.kindred.value} {c.character_class.value}")
            
            # Log some history
            print("\n3. Logging game history...")
            manager.log_history(
                world.campaign_id, turn_number=1, event_type="action",
                player_input="We enter the village of Prigwort",
                dm_response="The fog-shrouded village appears before you..."
            )
            manager.log_history(
                world.campaign_id, turn_number=2, event_type="dialogue",
                player_input="I talk to the innkeeper",
                dm_response="The grizzled innkeeper nods slowly..."
            )
            
            history = manager.get_recent_history(world.campaign_id)
            print(f"   Logged {len(history)} events")
            
            # Create a combat
            print("\n4. Starting a combat encounter...")
            combat = CombatState(
                campaign_id=world.campaign_id,
                is_active=True,
                round_number=1,
                party_combatants=[fighter.character_id, mage.character_id],
                enemies=[
                    Enemy(name="Goblin Scout", monster_type="goblin",
                          hp_current=4, hp_max=4, ac=13, morale_score=7),
                    Enemy(name="Goblin Warrior", monster_type="goblin",
                          hp_current=6, hp_max=6, ac=14, morale_score=8),
                ],
            )
            manager.start_combat(combat)
            print(f"   Combat started: {len(combat.party_combatants)} vs {len(combat.enemies)}")
            
            # Save session
            print("\n5. Saving session...")
            save_id = manager.save_session(
                world.campaign_id,
                "Before the Big Fight",
                "About to face the goblins"
            )
            print(f"   Saved: {save_id}")
            
            # Simulate damage
            print("\n6. Simulating combat damage...")
            fighter.take_damage(5)
            manager.update_character(fighter)
            print(f"   {fighter.name} took 5 damage, now at {fighter.hp_current}/{fighter.hp_max} HP")
            
            # Restore from save
            print("\n7. Restoring from save...")
            manager.restore_session(save_id)
            restored_fighter = manager.get_character(fighter.character_id)
            print(f"   {restored_fighter.name} restored to {restored_fighter.hp_current}/{restored_fighter.hp_max} HP")
            
            # Export for Foundry
            print("\n8. Exporting for Foundry VTT...")
            export = manager.export_for_foundry(world.campaign_id)
            print(f"   Exported {len(export['actors'])} actors")
            print(f"   System: {export['system']}")
            
            # Statistics
            print("\n9. Campaign statistics...")
            stats = manager.get_statistics(world.campaign_id)
            for key, value in stats.items():
                print(f"   {key}: {value}")
    
    finally:
        # Cleanup
        os.unlink(db_path)
    
    print("\n" + "=" * 60)
    print("DEMONSTRATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    # Run demo
    run_demo()
    
    # Run tests
    print("\n\nRunning pytest tests...")
    pytest.main([__file__, "-v", "--tb=short"])
