import { describe, expect, it } from "vitest";
import { toLearningPlanNode } from "../api/learning";

const node = { knowledge_key: "n1_1", title: "Variables", description: "Read an assignment", order_index: 0,
  is_core: true, prerequisite_keys: [], required_capabilities: ["python"] };

describe("explicit plan catalog identity", () => {
  it("retains the course step and optional exact catalog key", () => {
    expect(toLearningPlanNode(node)).toEqual(node);
    expect(toLearningPlanNode({ ...node, catalog_knowledge_key: null })).not.toBeNull();
    expect(toLearningPlanNode({ ...node, catalog_knowledge_key: "python.variables" })).toMatchObject({
      knowledge_key: "n1_1", catalog_knowledge_key: "python.variables",
    });
  });
  it.each(["", "Python Variables", "../python.variables", 2, {}])("rejects malformed optional mapping %j", (value) => {
    expect(toLearningPlanNode({ ...node, catalog_knowledge_key: value })).toBeNull();
  });
});
