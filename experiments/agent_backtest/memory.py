"""Memoria del agente: reflexiones episodicas + reglas destiladas con evidencia.

El contexto NO crece con la temporada: al prompt entran las reglas activas
(pocas) + las ultimas 3 reflexiones + la calibracion agregada. Es la destilacion
lo que convierte el log en aprendizaje (protocolo agent-lab, H5/H9).
"""
from __future__ import annotations

import json
from pathlib import Path


class Memoria:
    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.exists():
            d = json.loads(self.path.read_text())
        else:
            d = {"reglas": [], "reflexiones": [], "calibracion": []}
        self.reglas: list = d["reglas"]
        self.reflexiones: list = d["reflexiones"]
        self.calibracion: list = d["calibracion"]
        self.jugadores: dict = d.get("jugadores", {})

    def guardar(self) -> None:
        self.path.write_text(json.dumps(
            {"reglas": self.reglas, "reflexiones": self.reflexiones,
             "calibracion": self.calibracion, "jugadores": self.jugadores},
            ensure_ascii=False, indent=1))

    def registrar_call_jugador(self, gw: int, pid: int, nombre: str,
                               factor: float, minutos, pts) -> None:
        """Como salio cada call por jugador: el antidoto contra reincidir en un error."""
        self.jugadores.setdefault(str(pid), []).append(
            {"gw": gw, "nombre": nombre, "factor": factor, "min": minutos, "pts": pts})
        self.guardar()

    def registrar_reflexion(self, gw: int, salida: dict) -> None:
        self.reflexiones.append({"gw": gw, **salida})
        for r in salida.get("reglas_propuestas", []):
            # una regla nueva entra como candidata; si ya existe una igual, suma evidencia
            existente = next((x for x in self.reglas if x["regla"] == r.get("regla")), None)
            if existente:
                existente["evidencia"].append(r.get("evidencia", f"GW{gw}"))
                # la promocion a firme es PROGRAMATICA (>=3 evidencias), no del agente
                if len(existente["evidencia"]) >= 3:
                    existente["confianza"] = "firme"
            else:
                # toda regla nueva nace candidata, diga lo que diga el agente
                self.reglas.append({"regla": r.get("regla", ""),
                                    "confianza": "candidata",
                                    "nacida_gw": gw,
                                    "evidencia": [r.get("evidencia", f"GW{gw}")]})
        self.guardar()

    def registrar_calibracion(self, gw: int, expected: float, realized: int) -> None:
        self.calibracion.append({"gw": gw, "expected": expected, "realized": realized})
        self.guardar()

    def bloque_prompt(self) -> str:
        if not (self.reglas or self.reflexiones):
            return ""
        partes = ["\nTU MEMORIA (destilada de jornadas anteriores):"]
        calls = [(c["gw"], pid, c) for pid, hist in self.jugadores.items() for c in hist]
        if calls:
            partes.append("TUS CALLS RECIENTES POR JUGADOR (factor que aplicaste → que hizo despues).")
            partes.append("NO repitas una penalizacion que ya fallo salvo señal NUEVA:")
            for gw, pid, c in sorted(calls)[-10:]:
                veredicto = "FALLO (jugo y rindio)" if (c["factor"] < 0.8 and (c["min"] or 0) >= 60 and (c["pts"] or 0) >= 2) \
                    else ("acierto" if c["factor"] < 0.8 and (c["min"] or 0) < 45 else "neutro")
                partes.append(f"  GW{gw} {c['nombre']} (id {pid}): factor {c['factor']} → "
                              f"{c['min']} min, {c['pts']} pts [{veredicto}]")
        for r in self.reglas[-8:]:
            ev = "; ".join(r["evidencia"][-2:])
            partes.append(f"[REGLA {r['confianza']} | GW{r['nacida_gw']} | ev: {ev}] {r['regla']}")
        for rf in self.reflexiones[-3:]:
            for x in rf.get("reflexiones", [])[:2]:
                partes.append(f"[GW{rf['gw']} {x.get('resultado','?')}/"
                              f"{x.get('veredicto_proceso','?')}] {x.get('leccion','')}")
        cerradas = [c for c in self.calibracion if c.get("realized") is not None]
        if cerradas:
            esp = sum(c["expected"] for c in cerradas)
            rea = sum(c["realized"] for c in cerradas)
            partes.append(f"[CALIBRACION] {len(cerradas)} intervenciones con efecto: "
                          f"prometiste {esp:+.1f} xp, entregaste {rea:+d} pts reales.")
        return "\n".join(partes) + "\n"
