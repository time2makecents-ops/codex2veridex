from __future__ import annotations

import json
import io
import os
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from animation_studio import AnimationStudio, default_project, normalize_project


class AnimationStudioTests(unittest.TestCase):
    def test_eternia_starter_is_commercial_safe_2_5d(self) -> None:
        project = default_project()
        self.assertEqual(project["title"], "Eternia Late Night")
        self.assertEqual(project["visual_style"], "2.5D cut-out")
        self.assertEqual(project["release_intent"], "Commercial-safe")
        self.assertEqual(project["frame_rate"], 24)
        self.assertIn("Main desk set", project["sets"])
        self.assertIn("Band member template", project["characters"])

    def test_project_normalization_and_versioned_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            studio = AnimationStudio(Path(temporary))
            project = normalize_project({
                "title": "Eternia Late Night",
                "frame_rate": 29,
                "sets": ["Main desk", "Main desk", "Band stage"],
                "characters": "Host\nGuest template",
                "assets": [{"asset_id": "host", "file_id": "file_host", "name": "Host", "role": "character", "width_percent": 38}],
                "storyboard": [{"shot_id": "opening", "title": "Cold open", "asset_id": "host", "description": "Host enters."}],
                "audio_tracks": [{"track_id": "voice", "file_id": "file_voice", "name": "Host voice", "track_type": "dialogue", "character": "Host", "shot_id": "opening"}],
                "mouth_rigs": [{"rig_id": "host-rig", "character": "Host", "base_asset_id": "host", "animation_mode": "jaw_flap", "shapes": {"A": "host", "F": "missing"}, "mouth_x_percent": 54, "mouth_height_percent": 128, "mouth_anchor_x_percent": 42, "mouth_anchor_y_percent": 110, "placement_calibrated": True, "registration_master_asset_id": "host", "registration_canvas_width": 1254, "registration_canvas_height": 1254, "mouth_asset_registrations": {"host": {"left_percent": -2.5, "top_percent": 1.5, "width_percent": 104.4}}}],
                "lipsync_takes": [{"take_id": "opening-take", "track_id": "voice", "rig_id": "host-rig", "recognizer": "phonetic", "extended_shapes": "HGX", "duration": 0.5, "mouth_cues": [{"start": 0, "end": 0.5, "value": "A"}], "manual_jaw_corrections": [{"correction_id": "fix-1", "time": 0.25, "opening_percent": 115, "blend_seconds": 0.01}]}],
            })
            first = studio.save_project("workspace_123", project)
            second = studio.save_project("workspace_123", {**first, "notes": "Pilot cold open"})
            self.assertEqual(first["project_version"], 1)
            self.assertEqual(second["project_version"], 2)
            self.assertEqual(second["frame_rate"], 24)
            self.assertEqual(second["sets"], ["Main desk", "Band stage"])
            self.assertEqual(second["assets"][0]["role"], "character")
            self.assertEqual(second["storyboard"][0]["description"], "Host enters.")
            self.assertEqual(second["audio_tracks"][0]["shot_id"], "opening")
            self.assertEqual(second["mouth_rigs"][0]["shapes"]["A"], "host")
            self.assertEqual(second["mouth_rigs"][0]["animation_mode"], "jaw_flap")
            self.assertEqual(second["mouth_rigs"][0]["shapes"]["F"], "")
            self.assertEqual(second["mouth_rigs"][0]["mouth_height_percent"], 128)
            self.assertEqual(second["mouth_rigs"][0]["mouth_anchor_x_percent"], 42)
            self.assertTrue(second["mouth_rigs"][0]["placement_calibrated"])
            self.assertEqual(second["mouth_rigs"][0]["registration_master_asset_id"], "host")
            self.assertEqual(second["mouth_rigs"][0]["mouth_asset_registrations"]["host"]["width_percent"], 104.4)
            self.assertEqual(second["mouth_rigs"][0]["mouth_anchor_y_percent"], 100)
            self.assertEqual(second["lipsync_takes"][0]["recognizer"], "phonetic")
            self.assertEqual(second["lipsync_takes"][0]["extended_shapes"], "GHX")
            self.assertEqual(second["lipsync_takes"][0]["manual_jaw_corrections"], [{"correction_id": "fix-1", "time": 0.25, "opening_percent": 100, "blend_seconds": 0.03}])
            self.assertEqual(studio.list_projects("workspace_123")[0]["notes"], "Pilot cold open")
            saved_projects = studio.list_projects("workspace_123")
            self.assertEqual([row["project_version"] for row in saved_projects], [2, 1])
            self.assertEqual(saved_projects[1]["revision_id"], "eternia-late-night-v1")
            self.assertEqual(saved_projects[1]["notes"], "")

    def test_detects_user_local_gimp_program_files_audacity_and_synfig(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = root / "Local"
            programs = root / "Program Files"
            gimp = local / "Programs" / "GIMP 3" / "bin" / "gimp-3.exe"
            audacity = programs / "Audacity" / "audacity.exe"
            synfig = programs / "Synfig" / "bin" / "synfigstudio.exe"
            gimp.parent.mkdir(parents=True)
            audacity.parent.mkdir(parents=True)
            synfig.parent.mkdir(parents=True)
            gimp.write_bytes(b"exe")
            audacity.write_bytes(b"exe")
            synfig.write_bytes(b"exe")
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local), "ProgramFiles": str(programs)}, clear=False), patch(
                "animation_studio.shutil.which", return_value=None
            ):
                tools = AnimationStudio.tools()
            self.assertEqual(tools["gimp"]["path"], str(gimp))
            self.assertEqual(tools["audacity"]["path"], str(audacity))
            self.assertEqual(tools["synfig"]["path"], str(synfig))
            self.assertNotIn("blender", tools)

    def test_launch_editor_opens_supported_source_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            studio = AnimationStudio(Path(temporary))
            source = Path(temporary) / "host.png"
            source.write_bytes(b"image")
            process = type("Process", (), {"pid": 42})()
            tools = {"gimp": {"name": "GIMP 3", "path": "C:/Tools/gimp-3.exe"}}
            with patch.object(studio, "tools", return_value=tools), patch(
                "animation_studio.subprocess.Popen", return_value=process
            ) as opened:
                result = studio.launch_editor("gimp", source)
            opened.assert_called_once_with(["C:/Tools/gimp-3.exe", str(source.resolve())], shell=False)
            self.assertEqual(result["status"], "launched")

    def test_launch_editor_opens_image_in_synfig(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            studio = AnimationStudio(Path(temporary))
            source = Path(temporary) / "set.sif"
            source.write_text("<canvas version=\"0.1\" />", encoding="utf-8")
            process = type("Process", (), {"pid": 43})()
            tools = {"synfig": {"name": "Synfig Studio", "path": "C:/Tools/synfigstudio.exe"}}
            with patch.object(studio, "tools", return_value=tools), patch(
                "animation_studio.subprocess.Popen", return_value=process
            ) as opened:
                result = studio.launch_editor("synfig", source)
            opened.assert_called_once_with(["C:/Tools/synfigstudio.exe", str(source.resolve())], shell=False)
            self.assertEqual(result["status"], "launched")
            self.assertEqual(result["tool"], "Synfig Studio")

    def test_build_synfig_starter_is_well_formed_and_references_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "skeletor & host.png"
            source.write_bytes(b"image")
            document = AnimationStudio.build_synfig_starter(source, "Eternia Opening")
            root = ET.fromstring(document)
            layer = root.find("layer")
            self.assertEqual(root.tag, "canvas")
            self.assertEqual(root.findtext("name"), "Eternia Opening")
            self.assertEqual(layer.get("type"), "import")
            self.assertEqual(layer.findtext("param[@name='filename']/string"), source.resolve().as_posix())

    def test_build_synfig_lipsync_preview_uses_full_audio_with_two_second_holds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {}
            for file_id, name in (("bg-file", "set.png"), ("host-file", "host.png"), ("jaw-file", "jaw.png"), ("voice-file", "voice.m4a")):
                path = root / name
                path.write_bytes(b"source")
                files[file_id] = {"file_id": file_id, "path": str(path)}
            project = normalize_project({
                "assets": [
                    {"asset_id": "bg", "file_id": "bg-file", "name": "set.png", "role": "background", "width_percent": 100},
                    {"asset_id": "host", "file_id": "host-file", "name": "host.png", "role": "character", "width_percent": 35, "x_percent": 50, "y_percent": 60},
                    {"asset_id": "jaw", "file_id": "jaw-file", "name": "jaw.png", "role": "prop"},
                ],
                "audio_tracks": [{"track_id": "voice", "file_id": "voice-file", "name": "voice.m4a"}],
                "mouth_rigs": [{
                    "rig_id": "skeletor", "character": "Skeletor", "base_asset_id": "host", "animation_mode": "jaw_flap",
                    "shapes": {"X": "jaw"}, "placement_calibrated": True, "mouth_x_percent": 50, "mouth_y_percent": 25,
                    "mouth_width_percent": 14, "mouth_height_percent": 66, "mouth_anchor_x_percent": 50, "mouth_anchor_y_percent": 8,
                }],
                "lipsync_takes": [{
                    "take_id": "take-1", "track_id": "voice", "rig_id": "skeletor", "duration": 3,
                    "mouth_cues": [{"start": 0, "end": 0.5, "value": "A"}, {"start": 0.5, "end": 1, "value": "X"}],
                }],
            })
            preview = AnimationStudio.build_synfig_lipsync_preview(project, files, "take-1", audio_duration_seconds=3.5)
            canvas = ET.fromstring(preview["content"])
            layers = canvas.findall("layer")
            jaw_layer = next(layer for layer in layers if layer.get("desc") == "Skeletor jaw")
            sound_layer = next(layer for layer in layers if layer.get("type") == "sound")
            waypoint_times = [row.get("time") for row in jaw_layer.findall("param[@name='br']/animated/waypoint")]
            self.assertEqual(canvas.get("end-time"), "7.500s")
            self.assertEqual(preview["audio_duration"], 3.5)
            self.assertEqual(sound_layer.find("param[@name='delay']/time").get("value"), "2.000s")
            self.assertIn("2.000s", waypoint_times)
            self.assertIn("5.500s", waypoint_times)
            open_waypoint = next(row for row in jaw_layer.findall("param[@name='br']/animated/waypoint") if row.get("time") == "2.000s")
            open_y = float(open_waypoint.findtext("vector/y"))
            closed_waypoint = next(row for row in jaw_layer.findall("param[@name='br']/animated/waypoint") if row.get("time") == "5.500s")
            closed_y = float(closed_waypoint.findtext("vector/y"))
            self.assertLess(open_y, closed_y)
            project["lipsync_takes"][0]["manual_jaw_points"] = [
                {"time": 0, "opening_percent": 0},
                {"time": 1, "opening_percent": 100},
                {"time": 2, "opening_percent": 0},
            ]
            manual_preview = AnimationStudio.build_synfig_lipsync_preview(project, files, "take-1", audio_duration_seconds=3.5)
            manual_canvas = ET.fromstring(manual_preview["content"])
            manual_jaw = next(row for row in manual_canvas.findall("layer") if row.get("desc") == "Skeletor jaw")
            manual_waypoints = manual_jaw.findall("param[@name='br']/animated/waypoint")
            manual_peak = next(row for row in manual_waypoints if row.get("time") == "3.000s")
            self.assertEqual(manual_peak.get("after"), "linear")
            self.assertEqual(len(manual_canvas.findall("layer")), 4)
            project["lipsync_takes"][0]["manual_jaw_points"] = []
            project["lipsync_takes"][0]["manual_jaw_segments"] = [{
                "start": 0.25,
                "end": 0.75,
                "points": [{"time": 0.25, "opening_percent": 0}, {"time": 0.75, "opening_percent": 100}],
            }]
            segmented_preview = AnimationStudio.build_synfig_lipsync_preview(project, files, "take-1", audio_duration_seconds=3.5)
            segmented_canvas = ET.fromstring(segmented_preview["content"])
            segmented_jaw = next(row for row in segmented_canvas.findall("layer") if row.get("desc") == "Skeletor jaw")
            segmented_times = [row.get("time") for row in segmented_jaw.findall("param[@name='br']/animated/waypoint")]
            self.assertIn("2.000s", segmented_times)
            self.assertIn("2.250s", segmented_times)
            self.assertIn("2.750s", segmented_times)

            project["lipsync_takes"][0]["manual_jaw_segments"] = []
            project["lipsync_takes"][0]["manual_jaw_corrections"] = [{
                "correction_id": "fix-1", "time": 1.5, "opening_percent": 100, "blend_seconds": 0.12,
            }]
            corrected_preview = AnimationStudio.build_synfig_lipsync_preview(project, files, "take-1", audio_duration_seconds=3.5)
            corrected_canvas = ET.fromstring(corrected_preview["content"])
            corrected_jaw = next(row for row in corrected_canvas.findall("layer") if row.get("desc") == "Skeletor jaw")
            corrected_waypoints = {row.get("time"): row for row in corrected_jaw.findall("param[@name='br']/animated/waypoint")}
            self.assertIn("2.000s", corrected_waypoints)
            self.assertIn("3.380s", corrected_waypoints)
            self.assertIn("3.500s", corrected_waypoints)
            self.assertIn("3.620s", corrected_waypoints)
            self.assertEqual(corrected_waypoints["3.380s"].get("before"), "constant")
            self.assertEqual(corrected_waypoints["3.380s"].get("after"), "linear")
            self.assertEqual(corrected_waypoints["3.620s"].get("before"), "linear")
            self.assertEqual(corrected_waypoints["3.620s"].get("after"), "constant")

            project["lipsync_takes"][0]["manual_jaw_corrections"].append({
                "correction_id": "fix-2", "time": 1.6, "opening_percent": 40, "blend_seconds": 0.12,
            })
            overlapping_preview = AnimationStudio.build_synfig_lipsync_preview(project, files, "take-1", audio_duration_seconds=3.5)
            overlapping_canvas = ET.fromstring(overlapping_preview["content"])
            overlapping_jaw = next(row for row in overlapping_canvas.findall("layer") if row.get("desc") == "Skeletor jaw")
            overlapping_times = [row.get("time") for row in overlapping_jaw.findall("param[@name='br']/animated/waypoint")]
            self.assertIn("3.500s", overlapping_times)
            self.assertIn("3.600s", overlapping_times)
            self.assertIn("3.720s", overlapping_times)

    def test_skeletor_rig_migrates_to_measured_desk_host_placement(self) -> None:
        project = normalize_project({
            "assets": [{"asset_id": "host", "file_id": "host-file", "role": "character"}],
            "mouth_rigs": [{"rig_id": "skeletor", "character": "Skeletor", "base_asset_id": "host"}],
        })
        rig = project["mouth_rigs"][0]
        self.assertEqual(rig["stage_placement_preset"], "desk_host")
        self.assertEqual(rig["stage_x_percent"], 80.97)
        self.assertEqual(rig["stage_y_percent"], 43.12)
        self.assertEqual(rig["stage_width_percent"], 22)
        self.assertEqual(rig["jaw_open_strength_percent"], 200)

    def test_non_skeletor_rig_defaults_to_standard_jaw_strength(self) -> None:
        project = normalize_project({
            "assets": [{"asset_id": "host", "file_id": "host-file", "role": "character"}],
            "mouth_rigs": [{"rig_id": "host", "character": "Human host", "base_asset_id": "host"}],
        })
        self.assertEqual(project["mouth_rigs"][0]["jaw_open_strength_percent"], 100)

    def test_build_shot_package_contains_selected_media_manifest_and_cues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            studio = AnimationStudio(root)
            background = root / "desk.png"
            host = root / "host.png"
            jaw = root / "jaw.png"
            voice = root / "voice.wav"
            for path, content in ((background, b"background"), (host, b"host"), (jaw, b"jaw"), (voice, b"voice")):
                path.write_bytes(content)
            project = normalize_project({
                "project_id": "eternia-late-night",
                "storyboard": [{"shot_id": "opening", "title": "Opening", "asset_id": "desk", "duration_seconds": 3}],
                "assets": [
                    {"asset_id": "desk", "file_id": "file-desk", "name": "desk.png", "role": "background"},
                    {"asset_id": "host", "file_id": "file-host", "name": "host.png", "role": "character"},
                    {"asset_id": "jaw", "file_id": "file-jaw", "name": "jaw.png", "role": "prop"},
                ],
                "audio_tracks": [{"track_id": "voice", "file_id": "file-voice", "name": "voice.wav", "shot_id": "opening"}],
                "mouth_rigs": [{"rig_id": "skeletor", "character": "Skeletor", "base_asset_id": "host", "animation_mode": "jaw_flap", "shapes": {"X": "jaw"}}],
                "lipsync_takes": [{"take_id": "take-1", "track_id": "voice", "rig_id": "skeletor", "mouth_cues": [{"start": 0, "end": 0.5, "value": "A"}]}],
            })
            package = studio.build_shot_package(project, "opening", {
                "file-desk": {"file_id": "file-desk", "path": str(background)},
                "file-host": {"file_id": "file-host", "path": str(host)},
                "file-jaw": {"file_id": "file-jaw", "path": str(jaw)},
                "file-voice": {"file_id": "file-voice", "path": str(voice)},
            })
            with zipfile.ZipFile(io.BytesIO(package["content"])) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("shot-manifest.json"))
                cues = json.loads(archive.read("lip-sync-cues.json"))
            self.assertIn("README.txt", names)
            self.assertIn("assets/desk.png", names)
            self.assertIn("assets/host.png", names)
            self.assertIn("assets/jaw.png", names)
            self.assertIn("audio/voice.wav", names)
            self.assertEqual(manifest["package_type"], "veridex_synfig_shot")
            self.assertEqual(manifest["shot"]["shot_id"], "opening")
            self.assertEqual(len(manifest["assets"]), 3)
            self.assertEqual(len(manifest["audio_tracks"]), 1)
            self.assertEqual(cues["takes"][0]["mouthCues"][0]["value"], "A")

    def test_attach_render_records_a_versioned_project_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            studio = AnimationStudio(root)
            project = normalize_project({"project_id": "pilot", "storyboard": [{"shot_id": "opening", "title": "Opening"}]})
            render = root / "opening.mp4"
            render.write_bytes(b"render")
            saved = studio.attach_render("workspace_123", project, "opening", {
                "file_id": "file-render",
                "source_session_id": "session_123",
                "name": "opening.mp4",
                "path": str(render),
            })
            self.assertEqual(saved["project_version"], 1)
            self.assertEqual(saved["rendered_shots"][0]["shot_id"], "opening")
            self.assertEqual(saved["rendered_shots"][0]["format"], "mp4")

    def test_generate_lipsync_validates_and_returns_reviewable_cues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            studio = AnimationStudio(Path(temporary))
            audio = Path(temporary) / "host.wav"
            audio.write_bytes(b"RIFF test")

            def fake_run(command, **_kwargs):
                output = Path(command[command.index("-o") + 1])
                output.write_text(json.dumps({"mouthCues": [
                    {"start": 0.0, "end": 0.1, "value": "X"},
                    {"start": 0.1, "end": 0.5, "value": "D"},
                ]}), encoding="utf-8")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("animation_studio.shutil.which", return_value="C:/Tools/rhubarb.exe"), patch(
                "animation_studio.subprocess.run", side_effect=fake_run
            ):
                result = studio.generate_lipsync(audio, "Welcome to Eternia.")

            self.assertEqual(result["generator"], "Rhubarb Lip Sync")
            self.assertEqual(len(result["mouthCues"]), 2)
            self.assertEqual(result["duration"], 0.5)
            self.assertEqual(result["recognizer"], "pocketSphinx")
            self.assertEqual(result["extended_shapes"], "GHX")

    def test_generate_lipsync_converts_non_native_audio_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            studio = AnimationStudio(Path(temporary))
            audio = Path(temporary) / "host.mp3"
            original = b"original mp3"
            audio.write_bytes(original)
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                if "-o" not in command:
                    Path(command[-1]).write_bytes(b"RIFF converted")
                else:
                    output = Path(command[command.index("-o") + 1])
                    output.write_text(json.dumps({"mouthCues": [{"start": 0, "end": 0.25, "value": "B"}]}), encoding="utf-8")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            tools = {
                "rhubarb": {"path": "C:/Tools/rhubarb.exe"},
                "ffmpeg": {"path": "C:/Tools/ffmpeg.exe"},
            }
            with patch.object(studio, "tools", return_value=tools), patch(
                "animation_studio.subprocess.run", side_effect=fake_run
            ):
                result = studio.generate_lipsync(audio, recognizer="phonetic", extended_shapes="H")

            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0], "C:/Tools/ffmpeg.exe")
            self.assertTrue(str(calls[1][-1]).endswith("analysis.wav"))
            self.assertEqual(audio.read_bytes(), original)
            self.assertEqual(result["recognizer"], "phonetic")
            self.assertEqual(result["extended_shapes"], "H")

    def test_generate_lipsync_reports_missing_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            studio = AnimationStudio(Path(temporary))
            audio = Path(temporary) / "host.wav"
            audio.write_bytes(b"RIFF test")
            with patch.object(studio, "tools", return_value={"rhubarb": {"path": ""}}):
                with self.assertRaisesRegex(RuntimeError, "not installed"):
                    studio.generate_lipsync(audio)


if __name__ == "__main__":
    unittest.main()
