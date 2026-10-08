import { defineTool } from 'eve/tools';
import { always } from 'eve/tools/approval';
import { z } from 'zod';
import { knowledgeApi } from '../lib/knowledge-api';
export default defineTool({
 description:'Save a LOCAL draft support ticket after the user requests a handoff. Does not contact any external support desk. Reuse the same request_key when retrying.',
 approval:always(),
 inputSchema:z.object({query:z.string().min(1).max(2000),citation_ids:z.array(z.string()),request_key:z.string().min(1).max(120)}),
 execute:async input=>knowledgeApi('/api/tickets',input),
});
