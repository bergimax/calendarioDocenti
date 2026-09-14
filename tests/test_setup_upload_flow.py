"""
End-to-end test matching the frontend's actual setup flow (see
frontend/src/routes/setup.tsx): each file is uploaded separately via its own
/api/*/upload endpoint, and POST /api/setup/validate is then called with
just {"file_ids": [...]} rather than repeating each file's raw content.
"""


def _upload(client, path, filename, content):
    r = client.post(path, files={"file": (filename, content, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_setup_via_individual_uploads_and_file_ids(client):
    file_ids = []

    file_ids.append(
        _upload(
            client, "/api/calendar/upload", "calendario.csv",
            b"data,ore_max_giornata,flag_chiusura\n"
            b"2026-04-06,6,false\n2026-04-07,6,false\n2026-04-08,6,false\n"
            b"2026-04-09,6,false\n2026-04-10,6,false\n",
        )["file_id"]
    )
    file_ids.append(
        _upload(
            client, "/api/teachers/upload", "docenti.csv",
            b"nome,email,tipo\nProf Alfa,alfa@x.it,ASSUNTO\n",
        )["file_id"]
    )
    file_ids.append(
        _upload(client, "/api/classes/upload", "classi.csv", b"nome,n_studenti\n1A,20\n")["file_id"]
    )
    file_ids.append(
        _upload(
            client, "/api/subjects/upload", "materie.csv",
            b"nome,tipo,peso_cognitivo\nMatematica,TEORIA,ALTO\n",
        )["file_id"]
    )
    file_ids.append(
        _upload(
            client, "/api/assignments/upload", "assegnazioni.csv",
            b"docente_nome,classe_nome,materia_nome,ore_anno\nProf Alfa,1A,Matematica,90\n",
        )["file_id"]
    )

    # Exactly what the frontend sends: no raw content, just the ids.
    r = client.post("/api/setup/validate", json={"file_ids": file_ids})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_proceed"] is True, body["results"]
    for file_type in ("calendario", "docenti", "classi", "materie", "assegnazioni", "accoppiamenti"):
        assert body["results"][file_type]["success"] is True, body["results"][file_type]

    r = client.post(
        "/api/setup/save",
        json={
            "file_ids": file_ids,
            "corrections_applied": [],
            "school_name": "Scuola Upload Flow",
            "school_year": "2025-2026",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "setup_complete"
    assert body["school_id"] == "sch_1"


def test_upload_rejects_wrong_extension(client):
    r = client.post(
        "/api/teachers/upload",
        files={"file": ("docenti.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 400
