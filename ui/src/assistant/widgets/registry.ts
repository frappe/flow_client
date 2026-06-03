// Maps a WidgetPart.component key -> a Vue component.
//
// The data layer only ever references widgets by string, so messages stay
// serializable and backend-ready. Register new inline components here.

import type { Component } from 'vue'
import MetricCard from './MetricCard.vue'

export const widgetRegistry: Record<string, Component> = {
	MetricCard,
}
