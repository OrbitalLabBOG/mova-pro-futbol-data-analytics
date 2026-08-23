from types import SimpleNamespace

from mova_fpl.engine.report import _transferencias, _vigencia


def test_preliminary_warning_blocks_promotion_while_prior_gw_is_unsettled():
    lines = _vigencia({
        "dias_al_deadline": 5.0,
        "event_context": {
            "preliminary": True,
            "prior_gw": 1,
            "prior_unstarted_fixtures": 1,
        },
    })
    text = "\n".join(lines)
    assert "GW1 no está asentada" in text
    assert "faltan 1 partido(s)" in text
    assert "No promover chips" in text


def test_transfer_section_names_operations_and_explicit_hit_cost():
    decision = SimpleNamespace(
        transfers_in=(3, 4), transfers_out=(1, 2), hits=1,
    )
    players = {element: {"name": name} for element, name in {
        1: "Sale A", 2: "Sale B", 3: "Entra C", 4: "Entra D",
    }.items()}
    text = "\n".join(_transferencias(decision, players, {"hit_cost": 4}))
    assert "Sale A, Sale B" in text
    assert "Entra C, Entra D" in text
    assert "−4 puntos" in text
