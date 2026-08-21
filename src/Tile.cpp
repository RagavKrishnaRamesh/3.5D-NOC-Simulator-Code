/*
    (C) Copyright 2025 CEA LIST. All Rights Reserved.
    Contributor(s): Davy Million (davy.million@cea.fr)
*/

#include "Tile.h"
#include "NoC.h"

const Coord Tile::getCoord() const {
    return parent_noc.getCoordFromLocalId(local_id);
}

