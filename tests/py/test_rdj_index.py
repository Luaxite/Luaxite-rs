"""tools/rdj_index.py: the front end that turns rustdoc JSON into the generator's data model."""
import re
import unittest
from pathlib import Path

from _common import FAKE, FAKE_RDJ, ROOT, read
import rdj
import rdj_index as ri
import zenpel_gen as gen

EVENT_VARIANTS = ["Init", "Login", "Chat", "Tick", "AddPlayer", "KeepAlive", "Disconnect", "ConnectionFailed", "Death"]


class Defs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = rdj.load_dir(FAKE_RDJ)
        cls.defs = ri.build_defs(cls.r)
        cls.impls = ri.build_impls(cls.r)

    def first(self, name):
        return self.defs[name][0]

    def test_core_types_are_found(self):
        for name in ["Client", "EntityRef", "BlockPos", "Vec3", "Event", "Direction", "WalkDirection", "PathfinderOpts", "ChatPacket",
                     "PlayerInfo", "Physics", "Menu", "ItemStack", "GameMode", "HitResult"]:
            self.assertIn(name, self.defs, name)

    def test_def_kinds(self):
        self.assertEqual(self.first("Event").kind, "enum")
        self.assertEqual(self.first("BlockPos").kind, "struct")
        self.assertEqual(self.first("Direction").kind, "enum")

    def test_event_enum_variants_in_source_order(self):
        names = [v["name"] for v in self.first("Event").variants]
        self.assertEqual(names, EVENT_VARIANTS)

    def test_variant_shapes(self):
        by = {v["name"]: v for v in self.first("Event").variants}
        self.assertEqual(by["Init"]["kind"], "unit")
        self.assertEqual(by["Chat"]["kind"], "tuple")
        self.assertEqual(by["Chat"]["types"][0][1], "ChatPacket")
        self.assertEqual(by["Init"]["doc"], "Right after the client is created.")

    def test_struct_fields_have_names_and_types(self):
        fields = {f[0]: f[1] for f in self.first("BlockPos").fields}
        self.assertEqual(sorted(fields), ["x", "y", "z"])

    def test_dropped_variants_are_recorded_not_lost(self):
        for defs in self.defs.values():
            for d in defs:
                self.assertIsInstance(d.dropped_variants, list)


class Impls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = rdj.load_dir(FAKE_RDJ)
        cls.impls = ri.build_impls(cls.r)

    def methods_of(self, owner):
        return {m.name: m for m in self.impls.methods if m.target == owner}

    def test_client_methods_include_the_basics(self):
        ms = self.methods_of("Client")
        for n in ["chat", "position", "health", "wait_ticks", "goto", "mine", "open_inventory", "walk", "attack", "physics"]:
            self.assertTrue(any(k.startswith(n) for k in ms), n)

    def test_entityref_methods(self):
        ms = self.methods_of("EntityRef")
        for n in ["position", "health", "attack", "physics", "attributes", "minecraft_id"]:
            self.assertIn(n, ms)

    def test_async_flag_matches_signature(self):
        for m in self.impls.methods:
            self.assertEqual(m.is_async, re.search(r"\basync fn\b", m.sig) is not None, m.sig)

    def test_every_method_has_a_target_and_source_file(self):
        for m in self.impls.methods:
            self.assertTrue(m.target and m.file and m.sig)

    def test_receiver_is_set_for_methods_and_none_for_assoc_fns(self):
        ms = self.methods_of("Client")
        self.assertIsNone(ms["fake"].receiver)
        self.assertIsNotNone(ms["position"].receiver)

    def test_goal_impls_and_client_traits(self):
        self.assertEqual(self.impls.goal_impls, {"BlockPosGoal", "XZGoal", "ReachBlockPosGoal"})
        self.assertEqual(self.impls.client_traits, {"PathfinderClientExt"})

    def test_hidden_fns_are_reported_with_a_decision(self):
        for target, name, decision in self.impls.hidden:
            self.assertIn(decision, {"kept", "skipped"})


class CfgGates(unittest.TestCase):
    SRC = 'pub enum Event {\n    Init,\n    #[cfg(feature = "packet-event")]\n    Packet(Arc<P>),\n    Chat(ChatPacket),\n}\n'

    def test_variant_cfgs_are_read_from_source(self):
        got = ri.enum_variant_cfgs(self.SRC, "Event")
        self.assertEqual(got["Init"], [])
        self.assertEqual(got["Packet"], ['#[cfg(feature = "packet-event")]'])
        self.assertEqual(got["Chat"], [])

    def test_unknown_enum_is_none(self):
        self.assertIsNone(ri.enum_variant_cfgs(self.SRC, "Nope"))

    def test_cfg_in_comment_or_string_is_ignored(self):
        src = 'pub enum E {\n    // #[cfg(feature = "x")]\n    A,\n    B, /* #[cfg(x)] */\n}\n'
        got = ri.enum_variant_cfgs(src, "E")
        self.assertEqual(got["A"], [])
        self.assertEqual(got["B"], [])


class Freshness(unittest.TestCase):
    def test_fixture_meta_matches_sources(self):
        self.assertIn(rdj.source_sha1(FAKE / "azalea"), (FAKE_RDJ / "azalea.meta").read_text())

    def test_stale_json_reports_an_unreadable_source_dir_instead_of_raising(self):
        r = rdj.load_dir(FAKE_RDJ)
        out = ri.stale_json(r, {"azalea": FAKE})
        self.assertTrue(out and "azalea.json" in out[0])

    def test_missing_json_message_names_the_script(self):
        msg = ri.missing_json(ROOT, ROOT / "no-such-dir")
        self.assertIn("rustdoc", msg.lower())


class Skips(unittest.TestCase):
    def test_skips_are_collected_with_reasons(self):
        skips = []
        ri.build_defs(rdj.load_dir(FAKE_RDJ), skips=skips)
        for s in skips:
            self.assertTrue(s)


if __name__ == "__main__":
    unittest.main()
