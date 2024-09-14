/** @odoo-module **/

import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { getColor, hexToRGBA } from "@web/core/colors/colors";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onWillStart, useEffect, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { cookie } from "@web/core/browser/cookie";



export class WooDashboardGraphField extends Component {
    static template = "pragtech_woo_commerce.WooDashboardGraphField";
    static props = {
        ...standardFieldProps,
        graphType: String,
    };

    setup() {
        super.setup()

        this.chart = null;
        this.canvasRef = useRef("canvas");
        this.data = '';
        if (this.props.record.data[this.props.name]) {
            this.data = JSON.parse(this.props.record.data[this.props.name]);
        }
        this.actionService = useService("action");
        this.ormService = useService("orm");
        this._rpc = useService("rpc");
        this.orm = useService("orm");

        onWillStart(async () => await loadBundle("web.chartjs_lib"));

        useEffect(() => {
            if (this.data) {
                this.renderChart();
            }

            return () => {
                if (this.chart) {
                    this.chart.destroy();
                }
            };
        });
    }

    /**
     * Instantiates a Chart (Chart.js lib) to render the graph according to
     * the current config.
     */
    renderChart() {
        if (this.chart) {
            this.chart.destroy();
        }
        let config;
        if (this.props.graphType === "line") {
            config = this.getLineChartConfig();
        } else if (this.props.graphType === "bar") {
            config = this.getBarChartConfig();
        }
        this.chart = new Chart(this.canvasRef.el, config);
    }

    getLineChartConfig() {
        const labels = this.data.values.map(function (pt) {
            return pt.x;
        });
        const color10 = getColor(10, cookie.get("color_scheme"));
        const borderColor = this.data.is_sample_data ? hexToRGBA(color10, 0.1) : color10;
        const backgroundColor = this.data.is_sample_data
            ? hexToRGBA(color10, 0.05)
            : hexToRGBA(color10, 0.2);
        return {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        backgroundColor,
                        borderColor,
                        data: this.data.values,
                        fill: "start",
                        label: this.data.key,
                        borderWidth: 2,
                    },
                ],
            },
            options: {
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        intersect: false,
                        position: "nearest",
                        caretSize: 0,
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true, // the origin of the y axis is always zero
                    },
                },
                maintainAspectRatio: false,
                elements: {
                    line: {
                        tension: 0.000001,
                    },
                },
            },
        };
    }

    getBarChartConfig() {
        const data = [];
        const labels = [];
        const backgroundColor = [];

        const color13 = getColor(13, cookie.get("color_scheme"));
        const color19 = getColor(19, cookie.get("color_scheme"));
        this.data.values.forEach((pt) => {
            data.push(pt.value);
            labels.push(pt.label);
            if (pt.type === "past") {
                backgroundColor.push(color13);
            } else if (pt.type === "future") {
                backgroundColor.push(color19);
            } else {
                backgroundColor.push("#ebebeb");
            }
        });
        return {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        backgroundColor,
                        data,
                        fill: "start",
                        label: this.data.key,
                    },
                ],
            },
            options: {
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        intersect: false,
                        position: "nearest",
                        caretSize: 0,
                    },
                },
                scales: {
                    x: {
                        position: 'bottom'
                    },
                    y: {
                        position: 'left',
                        ticks: {
                            beginAtZero: true
                        },
                    }
                },
                maintainAspectRatio: false,
                elements: {
                    line: {
                        tension: 0.000001,
                    },
                },
            },
        };
    }

    async _sortOrders(e) {
        const [record] = await this.orm.read(this.props.record.resModel, [this.props.record.resId], ["dashboard_graph_data"], { context: {'sort':  e.currentTarget.value} });
        this.data = JSON.parse(record.dashboard_graph_data);
        this.renderChart();
    }

    _SyncedProducts() {
        return this.actionService.doAction(this.data.product_data.product_action, {})
    }

    _SyncedCustomers() {
        return this.actionService.doAction(this.data.customer_data.customer_action, {})
    }

    _SyncedOrders() {
        return this.actionService.doAction(this.data.order_data.order_action, {})
    }

    _SyncedTaxes() {
        return this.actionService.doAction(this.data.tax_data.tax_action, {})
    }

    _SyncedAttributes() {
         return this.actionService.doAction(this.data.attribute_data.attribute_action, {})
    }

    _SyncedCategories() {
        return this.actionService.doAction(this.data.category_data.category_action, {})
    }

}


export const wooDashboardGraphField = {
    component: WooDashboardGraphField,
    supportedTypes: ["text"],
    extractProps: ({ attrs }) => ({
        graphType: attrs.graph_type,
    }),
};

registry.category("fields").add("woo_dashboard_graph", wooDashboardGraphField);