import { useNavigate } from "react-router-dom";
import { useUI, type SelectionKind } from "@/store/ui";

/** Navigate to the Digital Twin, select the item and fly the camera to its available 3D location. */
export function useShowIn3D() {
  const nav = useNavigate();
  const requestFocus = useUI((s) => s.requestFocus);
  return (kind: SelectionKind, id: string) => {
    requestFocus({ kind, id });
    nav("/twin");
  };
}
