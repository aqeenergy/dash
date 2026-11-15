"""Prueba de extremo a extremo del protocolo de citas, SIN clave (Gemini simulado).

    voz\\.venv\\Scripts\\python -m ia_web.test_citas
"""
import json

from fastapi.testclient import TestClient

from ia_web.servidor_simulado import app


def conversar(ws, pregunta):
    ws.send_text(json.dumps({"tipo": "texto", "texto": pregunta}))
    eventos = []
    while True:
        m = ws.receive()
        if m.get("bytes"):
            continue
        ev = json.loads(m["text"])
        eventos.append(ev)
        if ev["tipo"] in ("turno_completo", "error"):
            return eventos


def main():
    cliente = TestClient(app)
    assert cliente.get("/ia/modo").json() == {"simulado": True}
    salud = cliente.get("/ia/salud").json()
    print("Tablas cargadas:", len(salud["tablas"]), "| fragmentos:", salud["fragmentos_indexados"])
    with cliente.websocket_connect("/ws/voz") as ws:
        assert json.loads(ws.receive_text())["tipo"] == "listo"

        ev = conversar(ws, "¿Qué combustible ardió más rápido en el experimento FLEX?")
        tipos = [e["tipo"] for e in ev]
        print("Turno 1:", tipos)
        citas = [e for e in ev if e["tipo"] == "cita"]
        assert len(citas) == 1, citas
        c = citas[0]
        print("Cita:", c["turno"], c["id"], json.dumps(c["cita"], ensure_ascii=False))
        assert c["turno"] == 1 and c["id"] == 1
        assert c["cita"]["tipo"] == "tabla"
        assert (c["cita"]["investigacion"], c["cita"]["accesion"]) == ("FLEX", "PSI-69")
        assert c["cita"]["doi"] == "10.60555/mbq8-0451"
        assert c["cita"]["url"] == "https://doi.org/10.60555/mbq8-0451"
        assert "agrupadas por Fuel" in c["cita"]["consulta"], c["cita"]["consulta"]
        assert c["cita"]["filas"] > 0
        fin = ev[-1]
        assert fin["tipo"] == "turno_completo" and fin["turno"] == 1
        print("Respuesta:", "".join(e["texto"] for e in ev if e["tipo"] == "transcripcion_ia"))

        ev2 = conversar(ws, "Short circuit near a cotton fabric panel with forced ventilation")
        citas2 = [e for e in ev2 if e["tipo"] == "cita"]
        print("Turno 2:", [e["tipo"] for e in ev2])
        for e in citas2:
            print("  [%d] %s · %s (%s)" % (e["id"], e["cita"]["investigacion"], e["cita"]["accesion"], e["cita"]["tipo"]))
        assert all(e["turno"] == 2 for e in citas2) and ev2[-1]["turno"] == 2
    print("OK: citas FLEX · PSI-69, DOI y numeración de turnos correctos")


if __name__ == "__main__":
    main()
