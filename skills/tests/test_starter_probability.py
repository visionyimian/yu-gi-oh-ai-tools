#!/usr/bin/env python3
"""Tests for starter-probability skill."""

import sys
from itertools import combinations
from pathlib import Path

import pytest

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "starter-probability" / "scripts"))
from starter_probability import (
  calculate_probabilities,
  hypergeometric_pmf,
  joint_probability,
  to_yaml,
)


class TestHypergeometricPmf:
  """Test hypergeometric probability mass function."""

  def test_zero_successes_possible(self):
    """Test probability of drawing 0 target cards."""
    # 40 cards, 10 targets, draw 5, want 0 targets
    prob = hypergeometric_pmf(40, 10, 5, 0)
    assert 0 < prob < 1
    # C(30,5) / C(40,5)
    expected = 0.2166  # approximately
    assert abs(prob - expected) < 0.01

  def test_one_success(self):
    """Test probability of drawing exactly 1 target card."""
    prob = hypergeometric_pmf(40, 10, 5, 1)
    assert 0 < prob < 1
    expected = 0.4165  # approximately
    assert abs(prob - expected) < 0.01

  def test_impossible_negative_k(self):
    """Test that negative k returns 0."""
    assert hypergeometric_pmf(40, 10, 5, -1) == 0.0

  def test_impossible_k_greater_than_success_states(self):
    """Test that k greater than success states returns 0."""
    assert hypergeometric_pmf(40, 10, 5, 11) == 0.0

  def test_impossible_k_greater_than_draws(self):
    """Test that k greater than draws returns 0."""
    assert hypergeometric_pmf(40, 10, 5, 6) == 0.0

  def test_certainty_all_targets(self):
    """Test when all cards are targets."""
    # Drawing 5 cards from 5 targets means always 5
    prob = hypergeometric_pmf(5, 5, 5, 5)
    assert prob == 1.0

  def test_zero_targets_in_deck(self):
    """Test when there are no target cards."""
    prob = hypergeometric_pmf(40, 0, 5, 0)
    assert prob == 1.0

  def test_probabilities_sum_to_one(self):
    """Test that probabilities sum to 1."""
    probs = [hypergeometric_pmf(40, 10, 5, k) for k in range(6)]
    assert abs(sum(probs) - 1.0) < 0.0001


class TestCalculateProbabilities:
  """Test the calculate_probabilities function."""

  def test_basic_calculation(self):
    """Test basic probability calculation."""
    result = calculate_probabilities(40, 10, 5)
    assert result["deck_size"] == 40
    assert result["target_count"] == 10
    assert result["hand_size"] == 5
    assert "probabilities" in result
    assert len(result["probabilities"]) == 6  # 0-5 cards

  def test_probabilities_are_percentages(self):
    """Test that probabilities are returned as percentages."""
    result = calculate_probabilities(40, 10, 5)
    for prob in result["probabilities"].values():
      assert 0 <= prob <= 100

  def test_at_least_1_exists(self):
    """Test that at_least_1 is calculated."""
    result = calculate_probabilities(40, 10, 5)
    assert "at_least_1" in result
    assert 0 < result["at_least_1"] < 100

  def test_at_least_2_exists(self):
    """Test that at_least_2 is calculated."""
    result = calculate_probabilities(40, 10, 5)
    assert "at_least_2" in result
    assert result["at_least_2"] < result["at_least_1"]

  def test_small_deck(self):
    """Test with a small deck."""
    result = calculate_probabilities(10, 3, 5)
    assert result["deck_size"] == 10
    assert result["target_count"] == 3

  def test_large_deck(self):
    """Test with a large deck."""
    result = calculate_probabilities(60, 15, 5)
    assert result["deck_size"] == 60
    assert result["target_count"] == 15

  def test_zero_targets(self):
    """Test with zero target cards."""
    result = calculate_probabilities(40, 0, 5)
    assert result["probabilities"]["0"] == 100.0
    assert result["probabilities"]["1"] == 0.0
    assert result["at_least_1"] == 0.0

  def test_all_targets(self):
    """Test when all cards are targets."""
    result = calculate_probabilities(5, 5, 5)
    assert result["probabilities"]["5"] == 100.0
    assert result["probabilities"]["0"] == 0.0


class TestToYaml:
  """Test YAML output formatting."""

  def test_basic_yaml_output(self):
    """Test basic YAML string generation."""
    data = {"deck_size": 40, "target_count": 10}
    yaml_str = to_yaml(data)
    assert "deck_size: 40" in yaml_str
    assert "target_count: 10" in yaml_str

  def test_nested_dict(self):
    """Test nested dictionary in YAML."""
    data = {"deck_size": 40, "probabilities": {"0": 21.66, "1": 41.65}}
    yaml_str = to_yaml(data)
    assert "deck_size: 40" in yaml_str
    assert "probabilities:" in yaml_str
    assert "0: 21.66%" in yaml_str

  def test_float_percentages(self):
    """Test that floats get % suffix."""
    data = {"probability": 50.5}
    yaml_str = to_yaml(data)
    assert "probability: 50.5%" in yaml_str


class TestValidation:
  """Test input validation through main function."""

  def test_deck_size_exceeds_target_count(self, tmp_path):
    """Test that target count can equal deck size."""
    # This should work
    result = calculate_probabilities(5, 5, 5)
    assert result is not None

  def test_invalid_combination_hand_gt_deck(self):
    """Test that hand_size > deck_size returns all zeros (invalid edge case)."""
    # When hand_size exceeds deck_size, the math breaks - this is an invalid input
    # that should be validated in main(), not calculate_probabilities()
    result = calculate_probabilities(5, 3, 10)
    # All probabilities return 0 due to the hypergeometric constraints
    assert result["probabilities"]["0"] == 0.0

  def test_edge_case_minimum_values(self):
    """Test minimum valid values."""
    result = calculate_probabilities(1, 1, 1)
    assert result["probabilities"]["1"] == 100.0


class TestJointProbability:
  """两组牌同时/任一出现在的概率（二卡展开必备）。"""

  @staticmethod
  def brute_force(deck_size, group_a, group_b, hand_size):
    """直接枚举全部手牌，作为解析式的对照。"""
    cards = ["A"] * group_a + ["B"] * group_b + ["C"] * (deck_size - group_a - group_b)
    total = both = either = 0
    for combo in combinations(range(deck_size), hand_size):
      names = {cards[i] for i in combo}
      total += 1
      has_a = "A" in names
      has_b = "B" in names
      if has_a and has_b:
        both += 1
      if has_a or has_b:
        either += 1
    return total, both, either

  def test_both_matches_brute_force(self):
    total, both, _ = self.brute_force(10, 3, 4, 3)
    result = joint_probability(10, 3, 4, 3)
    assert result["both"] == pytest.approx(both / total * 100, abs=0.01)

  def test_either_matches_brute_force(self):
    total, _, either = self.brute_force(12, 5, 2, 4)
    result = joint_probability(12, 5, 2, 4)
    assert result["either"] == pytest.approx(either / total * 100, abs=0.01)

  def test_both_cannot_exceed_either(self):
    result = joint_probability(40, 11, 17, 5)
    assert 0 < result["both"] < result["either"] < 100

  def test_either_plus_neither_is_full(self):
    result = joint_probability(40, 4, 17, 5)
    assert result["either"] + result["neither"] == pytest.approx(100.0, abs=0.01)

  def test_overlapping_groups_rejected(self):
    """两组之和超过卡组大小说明有重叠，必须报错而不是算错。"""
    with pytest.raises(ValueError):
      joint_probability(40, 25, 20, 5)

  def test_negative_group_rejected(self):
    with pytest.raises(ValueError):
      joint_probability(40, -1, 5, 5)

  def test_zero_group(self):
    result = joint_probability(40, 0, 5, 5)
    assert result["both"] == 0.0
    # A 组为空时，「至少一张」退化成普通单组概率
    assert result["either"] == calculate_probabilities(40, 5, 5)["at_least_1"]
