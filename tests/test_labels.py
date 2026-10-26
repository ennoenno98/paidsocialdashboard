import math

from src.ingest.labels import (
    canonical_metric,
    normalise_er,
    parse_cw,
    parse_month,
    parse_number,
    parse_play_time,
)


def test_canonical_metric_synonyms():
    assert canonical_metric("AD Spent ") == "boost_spend"
    assert canonical_metric("Total Spent") == "boost_spend"
    assert canonical_metric("Boosting Spent") == "boost_spend"
    assert canonical_metric("Ad cost") == "boost_spend"
    assert canonical_metric("Overall") == "net_follows"
    assert canonical_metric("Overall Follows") == "net_follows"
    assert canonical_metric("Net Followers") == "net_follows"
    assert canonical_metric("Total Followers") == "followers"
    assert canonical_metric("Reach ") == "reach"
    assert canonical_metric("Number of IGS") == "n_igs"
    assert canonical_metric("Repost") == "reposts"
    assert canonical_metric("Video Views") == "video_views"
    assert canonical_metric("something odd") is None


def test_parse_cw_and_month():
    assert parse_cw("CW 01") == 1
    assert parse_cw("cw52") == 52
    assert parse_cw(12) == 12
    assert parse_cw("Reach") is None
    assert parse_month("Janury ") == 1
    assert parse_month("July ") == 7
    assert parse_month("November ") == 11
    assert parse_month("Sept") == 9
    assert parse_month("Okt") == 10
    assert parse_month("Budget") is None
    assert parse_month(None) is None


def test_parse_number():
    assert parse_number("1.234,5") == 1234.5
    assert parse_number("1,234.5") == 1234.5
    assert parse_number("3,5%") == 0.035
    assert parse_number(" 12 ") == 12
    assert math.isnan(parse_number("/"))
    assert math.isnan(parse_number("#DIV/0!"))
    assert math.isnan(parse_number("justus"))
    assert math.isnan(parse_number(None))


def test_parse_play_time():
    assert parse_play_time("1h12m") == 72
    assert parse_play_time("62h") == 3720
    assert parse_play_time("45m") == 45
    assert parse_play_time("1:30:00") == 90
    assert parse_play_time(15) == 15
    assert math.isnan(parse_play_time("/"))


def test_normalise_er():
    assert normalise_er(0.035) == 0.035
    assert normalise_er(3.5) == 0.035
    assert math.isnan(normalise_er(float("nan")))
