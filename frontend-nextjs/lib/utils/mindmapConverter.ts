import { MindMapNode, MindMapEdge } from '../api/mindmap';

/**
 * Convert backend node/edge structure to hierarchical tree structure for Markmap
 *
 * The backend returns a flat list of nodes and edges.
 * We need to convert this into a hierarchical structure for visualization.
 */

export interface TreeNode {
  id: string;
  content: string;
  children: TreeNode[];
  depth: number;
}

/**
 * Build hierarchical tree from flat nodes and edges
 */
export function buildTree(nodes: MindMapNode[], edges: MindMapEdge[]): TreeNode | null {
  if (nodes.length === 0) return null;

  // Create a map for quick node lookup
  const nodeMap = new Map<string, TreeNode>();

  // Initialize all nodes
  nodes.forEach(node => {
    nodeMap.set(node.id, {
      id: node.id,
      content: node.content,
      children: [],
      depth: 0,
    });
  });

  // Create adjacency list: parent -> children
  const childrenMap = new Map<string, string[]>();
  const parentMap = new Map<string, string>();

  edges.forEach(edge => {
    const children = childrenMap.get(edge.from_id) || [];
    children.push(edge.to_id);
    childrenMap.set(edge.from_id, children);
    parentMap.set(edge.to_id, edge.from_id);
  });

  // Find root node (node with no parent)
  let rootId: string | null = null;
  for (const node of nodes) {
    if (!parentMap.has(node.id)) {
      rootId = node.id;
      break;
    }
  }

  // If no root found (circular graph), use first node
  if (!rootId) {
    rootId = nodes[0].id;
  }

  // Build tree recursively
  function buildSubtree(nodeId: string, depth: number): TreeNode {
    const node = nodeMap.get(nodeId)!;
    node.depth = depth;

    const childIds = childrenMap.get(nodeId) || [];
    node.children = childIds.map(childId => buildSubtree(childId, depth + 1));

    return node;
  }

  return buildSubtree(rootId, 0);
}

/**
 * Convert tree structure to markdown format for Markmap
 * Markmap uses markdown headings to represent hierarchy
 */
export function treeToMarkdown(tree: TreeNode | null): string {
  if (!tree) return '';

  const lines: string[] = [];

  function traverse(node: TreeNode) {
    // Create markdown heading based on depth (# = level 1, ## = level 2, etc.)
    const heading = '#'.repeat(Math.max(1, node.depth + 1));
    lines.push(`${heading} ${node.content}`);

    // Traverse children
    node.children.forEach(child => traverse(child));
  }

  traverse(tree);
  return lines.join('\n\n');
}

/**
 * Main converter function: nodes + edges -> markdown
 */
export function convertToMarkdown(nodes: MindMapNode[], edges: MindMapEdge[]): string {
  const tree = buildTree(nodes, edges);
  return treeToMarkdown(tree);
}

/**
 * Alternative: Convert to D3 hierarchy format (if needed)
 */
export function convertToD3Hierarchy(nodes: MindMapNode[], edges: MindMapEdge[]): any {
  const tree = buildTree(nodes, edges);

  if (!tree) return null;

  function treeNodeToD3(node: TreeNode): any {
    return {
      name: node.content,
      value: node.id,
      children: node.children.length > 0
        ? node.children.map(child => treeNodeToD3(child))
        : undefined
    };
  }

  return treeNodeToD3(tree);
}
