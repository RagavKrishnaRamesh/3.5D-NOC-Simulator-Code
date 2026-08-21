#ifndef __NOXIMSELECTION_BUFFER_LEVEL_H__
#define __NOXIMSELECTION_BUFFER_LEVEL_H__

#include "SelectionStrategy.h"
#include "SelectionStrategies.h"
#include "../Router.h"

using namespace std;

class Selection_BUFFER_LEVEL : SelectionStrategy {
	public:
        RouteEntry apply(Router * router,
                         const vector<RouteEntry> & directions,
                         const RouteData & route_data) override;

        void perCycleUpdate(Router * router);

		static Selection_BUFFER_LEVEL * getInstance();

	private:
		Selection_BUFFER_LEVEL(){};
		~Selection_BUFFER_LEVEL(){};

		static Selection_BUFFER_LEVEL * selection_BUFFER_LEVEL;
		static SelectionStrategiesRegister selectionStrategiesRegister;
};

#endif
