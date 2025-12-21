"""
Tests for the Main Game Loop Module.

Tests game orchestration without requiring API calls.
"""

import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from main import (
    GameConfig,
    DolmenwoodGame,
    DolmenwoodCLI,
)
from data_models import (
    WorldState,
    DolmenwoodCharacter,
    Kindred,
    CharacterClass,
    Season,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def game_config(temp_data_dir):
    """Create a game config with temp directories."""
    return GameConfig(
        data_dir=temp_data_dir,
        database_path=f"{temp_data_dir}/game_state.db",
        vector_db_path=f"{temp_data_dir}/vectordb",
        pdf_dir=f"{temp_data_dir}/pdfs",
        use_vector_db=True,
        use_mock_embeddings=True,  # Don't call OpenAI
        anthropic_api_key="test-key",  # Fake key for testing
    )


@pytest.fixture
def game(game_config):
    """Create a game instance."""
    return DolmenwoodGame(game_config)


# =============================================================================
# GAME CONFIG TESTS
# =============================================================================

class TestGameConfig:
    """Test GameConfig class."""
    
    def test_default_config(self, temp_data_dir):
        """Test default configuration."""
        config = GameConfig(data_dir=temp_data_dir)
        
        assert config.dm_style == "evocative"
        assert config.rules_strictness == "balanced"
        assert config.use_vector_db is True
    
    def test_custom_config(self, temp_data_dir):
        """Test custom configuration."""
        config = GameConfig(
            data_dir=temp_data_dir,
            dm_style="terse",
            rules_strictness="strict",
            use_vector_db=False,
        )
        
        assert config.dm_style == "terse"
        assert config.rules_strictness == "strict"
        assert config.use_vector_db is False
    
    def test_directories_created(self, temp_data_dir):
        """Test that directories are created."""
        config = GameConfig(
            data_dir=temp_data_dir,
            pdf_dir=f"{temp_data_dir}/pdfs",
        )
        
        assert Path(config.data_dir).exists()
        assert Path(config.pdf_dir).exists()


# =============================================================================
# DOLMENWOOD GAME TESTS
# =============================================================================

class TestDolmenwoodGame:
    """Test DolmenwoodGame class."""
    
    def test_game_initialization(self, game):
        """Test game initializes correctly."""
        assert game is not None
        assert game._campaign_id is None
        assert game._world_state is None
    
    def test_initialize_components(self, game):
        """Test initializing all components."""
        game.initialize()
        
        assert game._state_manager is not None
        assert game._rules_retriever is not None
        assert game._dm is not None
    
    def test_start_new_campaign(self, game):
        """Test starting a new campaign."""
        campaign_id = game.start_new_campaign("Test Campaign")
        
        assert campaign_id is not None
        assert game._campaign_id == campaign_id
        assert game._world_state is not None
        assert game._world_state.campaign_name == "Test Campaign"
    
    def test_start_campaign_with_custom_settings(self, game):
        """Test starting campaign with custom settings."""
        campaign_id = game.start_new_campaign(
            campaign_name="Custom Campaign",
            starting_location="Castle Brackenwold",
            starting_hex="1010",
            season=Season.WINTER
        )
        
        assert game._world_state.current_location_name == "Castle Brackenwold"
        assert game._world_state.current_hex == "1010"
        assert game._world_state.season == Season.WINTER
    
    def test_list_campaigns_empty(self, game):
        """Test listing campaigns when empty."""
        campaigns = game.list_campaigns()
        
        assert campaigns == []
    
    def test_list_campaigns_with_data(self, game):
        """Test listing campaigns after creating some."""
        game.start_new_campaign("Campaign 1")
        game.start_new_campaign("Campaign 2")
        
        campaigns = game.list_campaigns()
        
        assert len(campaigns) == 2
        names = [c["name"] for c in campaigns]
        assert "Campaign 1" in names
        assert "Campaign 2" in names
    
    def test_load_campaign(self, game):
        """Test loading an existing campaign."""
        # Create and save a campaign
        campaign_id = game.start_new_campaign("Load Test")
        
        # Create new game instance
        game2 = DolmenwoodGame(game.config)
        
        # Load the campaign
        success = game2.load_campaign(campaign_id)
        
        assert success is True
        assert game2._campaign_id == campaign_id
        assert game2._world_state.campaign_name == "Load Test"
    
    def test_load_nonexistent_campaign(self, game):
        """Test loading a campaign that doesn't exist."""
        success = game.load_campaign("nonexistent-id")
        
        assert success is False
    
    def test_save_session(self, game):
        """Test saving a session."""
        game.start_new_campaign("Save Test")
        
        save_id = game.save_session("Manual Save")
        
        assert save_id is not None
    
    def test_save_session_no_campaign(self, game):
        """Test saving without an active campaign."""
        with pytest.raises(RuntimeError, match="No active campaign"):
            game.save_session()


# =============================================================================
# CHARACTER MANAGEMENT TESTS
# =============================================================================

class TestCharacterManagement:
    """Test character management functions."""
    
    def test_create_character(self, game):
        """Test creating a character."""
        game.start_new_campaign("Character Test")
        
        char_id = game.create_character(
            name="Test Hero",
            player_name="Test Player",
            kindred=Kindred.HUMAN,
            character_class=CharacterClass.FIGHTER,
            strength=16,
            dexterity=14,
            constitution=15,
            intelligence=10,
            wisdom=12,
            charisma=8,
        )
        
        assert char_id is not None
        
        # Character should be in party
        party = game.get_party()
        assert len(party) == 1
        assert party[0].name == "Test Hero"
    
    def test_create_character_no_campaign(self, game):
        """Test creating character without active campaign."""
        with pytest.raises(RuntimeError, match="No active campaign"):
            game.create_character(
                name="Test",
                player_name="Player",
                kindred=Kindred.HUMAN,
                character_class=CharacterClass.FIGHTER,
            )
    
    def test_get_party_empty(self, game):
        """Test getting party when empty."""
        game.start_new_campaign("Empty Party Test")
        
        party = game.get_party()
        
        assert party == []
    
    def test_get_party_multiple_characters(self, game):
        """Test getting party with multiple characters."""
        game.start_new_campaign("Multi Character Test")
        
        game.create_character(
            name="Fighter",
            player_name="Player 1",
            kindred=Kindred.HUMAN,
            character_class=CharacterClass.FIGHTER,
        )
        game.create_character(
            name="Mage",
            player_name="Player 2",
            kindred=Kindred.ELF,
            character_class=CharacterClass.MAGICIAN,
        )
        
        party = game.get_party()
        
        assert len(party) == 2
    
    def test_roll_new_character_stats(self, game):
        """Test rolling new character stats."""
        stats = game.roll_new_character_stats()
        
        assert "strength" in stats
        assert "intelligence" in stats
        assert "wisdom" in stats
        assert "dexterity" in stats
        assert "constitution" in stats
        assert "charisma" in stats
        
        # All values should be in valid range (4d6kh3 = 3-18)
        for value in stats.values():
            assert 3 <= value <= 18


# =============================================================================
# GAMEPLAY TESTS
# =============================================================================

class TestGameplay:
    """Test gameplay functions."""
    
    def test_get_session_summary_no_campaign(self, game):
        """Test session summary without campaign."""
        summary = game.get_session_summary()
        
        assert "No active campaign" in summary
    
    def test_get_session_summary_with_campaign(self, game):
        """Test session summary with active campaign."""
        game.start_new_campaign("Summary Test")
        
        summary = game.get_session_summary()
        
        assert "Summary Test" in summary
        assert "Prigwort" in summary
    
    def test_get_session_summary_with_party(self, game):
        """Test session summary includes party."""
        game.start_new_campaign("Party Summary Test")
        game.create_character(
            name="Hero",
            player_name="Player",
            kindred=Kindred.HUMAN,
            character_class=CharacterClass.FIGHTER,
        )
        
        summary = game.get_session_summary()
        
        assert "Hero" in summary
    
    def test_process_input_no_campaign(self, game):
        """Test processing input without active campaign."""
        with pytest.raises(RuntimeError, match="No active campaign"):
            game.process_input("I look around")
    
    def test_get_vector_db_stats(self, game):
        """Test getting vector DB statistics."""
        game.initialize()
        
        stats = game.get_vector_db_stats()
        
        assert isinstance(stats, dict)
        assert "rules" in stats
        assert "monsters" in stats


# =============================================================================
# CLI TESTS
# =============================================================================

class TestDolmenwoodCLI:
    """Test CLI interface."""
    
    def test_cli_initialization(self, game):
        """Test CLI initializes correctly."""
        cli = DolmenwoodCLI(game)
        
        assert cli.game is game
        assert cli.running is False
    
    def test_handle_help_command(self, game, capsys):
        """Test /help command."""
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/help")
        
        assert result is True
        captured = capsys.readouterr()
        assert "Available Commands" in captured.out
    
    def test_handle_quit_command(self, game):
        """Test /quit command returns False."""
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/quit")
        
        assert result is False
    
    def test_handle_roll_command(self, game, capsys):
        """Test /roll command."""
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/roll 2d6")
        
        assert result is True
        captured = capsys.readouterr()
        assert "🎲" in captured.out
    
    def test_handle_roll_invalid(self, game, capsys):
        """Test /roll with invalid notation."""
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/roll invalid")
        
        assert result is True
        captured = capsys.readouterr()
        assert "Invalid" in captured.out
    
    def test_handle_status_no_campaign(self, game, capsys):
        """Test /status without campaign."""
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/status")
        
        assert result is True
        captured = capsys.readouterr()
        assert "No active campaign" in captured.out
    
    def test_handle_status_with_campaign(self, game, capsys):
        """Test /status with active campaign."""
        game.start_new_campaign("Status Test")
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/status")
        
        assert result is True
        captured = capsys.readouterr()
        assert "Status Test" in captured.out
    
    def test_handle_list_empty(self, game, capsys):
        """Test /list with no campaigns."""
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/list")
        
        assert result is True
        captured = capsys.readouterr()
        assert "No saved campaigns" in captured.out
    
    def test_handle_list_with_campaigns(self, game, capsys):
        """Test /list with campaigns."""
        game.start_new_campaign("List Test 1")
        game.start_new_campaign("List Test 2")
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/list")
        
        assert result is True
        captured = capsys.readouterr()
        assert "List Test 1" in captured.out or "List Test 2" in captured.out
    
    def test_handle_party_no_campaign(self, game, capsys):
        """Test /party without campaign."""
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/party")
        
        assert result is True
        captured = capsys.readouterr()
        assert "No characters" in captured.out
    
    def test_handle_unknown_command(self, game, capsys):
        """Test unknown command."""
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/unknown")
        
        assert result is True
        captured = capsys.readouterr()
        assert "Unknown command" in captured.out
    
    def test_handle_new_with_args(self, game, capsys):
        """Test /new with campaign name argument."""
        cli = DolmenwoodCLI(game)
        
        result = cli.handle_command("/new Quick Campaign")
        
        assert result is True
        captured = capsys.readouterr()
        assert "Quick Campaign" in captured.out
        assert game._campaign_id is not None


# =============================================================================
# CLEANUP TESTS
# =============================================================================

class TestCleanup:
    """Test cleanup functionality."""
    
    def test_close_game(self, game):
        """Test closing game resources."""
        game.initialize()
        game.start_new_campaign("Close Test")
        
        game.close()
        
        assert game._state_manager is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
