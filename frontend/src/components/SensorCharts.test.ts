import { describe, expect, it } from "vitest";
import type { Device } from "@/api/types";
import { displaySource } from "./SensorCharts";

describe("displaySource — simulated and real data are never mixed", () => {
  const sim = { data_source: "simulated" } as Device;
  const real = { data_source: "real" } as Device;
  it("hides simulated devices outside simulated/all modes", () => {
    expect(displaySource(sim, "real")).toBe("__hidden__");
    expect(displaySource(sim, "uploaded")).toBe("__hidden__");
    expect(displaySource(sim, "simulated")).toBe("simulated");
  });
  it("shows only the selected genuine source for real devices", () => {
    expect(displaySource(real, "real")).toBe("real");
    expect(displaySource(real, "uploaded")).toBe("uploaded");
    expect(displaySource(real, "simulated")).toBe("__hidden__");
  });
  it("'all' shows each device's own native source, never a merged series", () => {
    expect(displaySource(real, "all")).toBe("real");
    expect(displaySource(sim, "all")).toBe("simulated");
  });
});
