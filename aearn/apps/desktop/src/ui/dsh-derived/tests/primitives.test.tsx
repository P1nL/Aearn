import { createRef, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  Button,
  DisclosureRow,
  DshDerivedRoot,
  IconCheck,
  Input,
  MessageText,
  Pill,
  StateDot,
  Tooltip,
} from "../index";

function ControlledDisclosure() {
  const [expanded, setExpanded] = useState(false);
  return (
    <DisclosureRow
      title="Think"
      expanded={expanded}
      onExpandedChange={setExpanded}
      summary="2 steps"
      contentId="thinking-steps"
    >
      <p>Public step</p>
    </DisclosureRow>
  );
}

describe("DSH-derived primitives", () => {
  it("provides the scoped root class", () => {
    render(<DshDerivedRoot data-testid="root">content</DshDerivedRoot>);
    expect(screen.getByTestId("root")).toHaveClass("aearn-dsh-derived");
  });

  it("makes busy buttons unavailable without hiding their label", () => {
    const onClick = vi.fn();
    render(<Button busy onClick={onClick}>保存</Button>);
    const button = screen.getByRole("button", { name: "保存" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps buttons and interactive pills keyboard reachable", async () => {
    const user = userEvent.setup();
    const onPillClick = vi.fn();
    render(
      <>
        <Button icon={<IconCheck />} aria-label="确认" variant="icon" />
        <Pill onClick={onPillClick}>筛选</Pill>
      </>,
    );

    await user.tab();
    expect(screen.getByRole("button", { name: "确认" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "筛选" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onPillClick).toHaveBeenCalledTimes(1);
  });

  it("forwards the input ref and exposes invalid state", () => {
    const ref = createRef<HTMLInputElement>();
    render(<Input ref={ref} aria-label="名称" invalid />);
    expect(ref.current).toBe(screen.getByRole("textbox", { name: "名称" }));
    expect(ref.current).toHaveAttribute("aria-invalid", "true");
  });

  it("uses a controlled native disclosure contract", async () => {
    const user = userEvent.setup();
    render(<ControlledDisclosure />);
    const toggle = screen.getByRole("button", { name: /Think/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "thinking-steps");
    expect(screen.getByText("Public step")).not.toBeVisible();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Public step")).toBeVisible();
  });

  it("associates enabled targets with their tooltip description", () => {
    render(
      <Tooltip label="发送消息">
        <button type="button">发送</button>
      </Tooltip>,
    );
    const button = screen.getByRole("button", { name: "发送" });
    const tooltip = screen.getByRole("tooltip", { hidden: true });
    expect(button).toHaveAttribute("aria-describedby", tooltip.id);
  });
  it("provides a tooltip label and disabled-target title fallback", () => {
    render(
      <Tooltip label="删除队列项" disabledTarget>
        <button type="button" disabled>删除</button>
      </Tooltip>,
    );
    expect(screen.getByRole("tooltip", { hidden: true })).toHaveTextContent("删除队列项");
    expect(screen.getByTitle("删除队列项")).toHaveAttribute("tabindex", "0");
  });

  it("renders literal message text without interpreting markup", () => {
    render(<MessageText text={'<img src=x onerror="alert(1)">\n下一行'} />);
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("renders semantic state dots without accessible noise", () => {
    const { container } = render(
      <span aria-label="运行中"><StateDot state="running" /></span>,
    );
    expect(container.querySelector('[data-state="running"]')).toHaveAttribute("aria-hidden", "true");
  });
});
