import { request } from "./client.js";

export const getMonthlyReport = (months) =>
  request(`/api/reports/monthly?months=${encodeURIComponent(months)}`);
