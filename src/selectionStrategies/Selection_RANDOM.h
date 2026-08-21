#ifndef __NOXIMSELECTION_RANDOM_H__
#define __NOXIMSELECTION_RANDOM_H__

#include "SelectionStrategy.h"
#include "SelectionStrategies.h"
#include "../Router.h"

using namespace std;

class Selection_RANDOM : SelectionStrategy {
	public:
        RouteEntry apply(Router * router,
                         const vector<RouteEntry> & directions,
                         const RouteData & route_data) override;
        void perCycleUpdate(Router * router);

		static Selection_RANDOM * getInstance();

	private:
		Selection_RANDOM(){};
		~Selection_RANDOM(){};

		static Selection_RANDOM * selection_RANDOM;
		static SelectionStrategiesRegister selectionStrategiesRegister;
};

#endif
